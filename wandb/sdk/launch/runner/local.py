import logging
import os
import signal
import subprocess
import sys

import wandb
from wandb.errors import LaunchException

from .abstract import AbstractRun, AbstractRunner
from ..docker import (
    build_docker_image,
    generate_docker_image,
    get_docker_command,
    pull_docker_image,
    validate_docker_env,
    validate_docker_installation,
)
from ..utils import (
    get_entry_point_command,
    PROJECT_DOCKER_ARGS,
    PROJECT_SYNCHRONOUS,
)


_logger = logging.getLogger(__name__)


class LocalSubmittedRun(AbstractRun):
    """
    Instance of ``AbstractRun`` corresponding to a subprocess launched to run an entry point
    command locally.
    """

    def __init__(self, command_proc):
        super().__init__()
        self.command_proc = command_proc

    @property
    def id(self):
        return self.command_proc.pid

    def wait(self):
        return self.command_proc.wait() == 0

    def cancel(self):
        # Interrupt child process if it hasn't already exited
        if self.command_proc.poll() is None:
            # Kill the the process tree rooted at the child if it's the leader of its own process
            # group, otherwise just kill the child
            try:
                if self.command_proc.pid == os.getpgid(self.command_proc.pid):
                    os.killpg(self.command_proc.pid, signal.SIGTERM)
                else:
                    self.command_proc.terminate()
            except OSError:
                # The child process may have exited before we attempted to terminate it, so we
                # ignore OSErrors raised during child process termination
                _logger.info(
                    "Failed to terminate child process (PID %s). The process may have already exited.",
                    self.command_proc.pid,
                )
            self.command_proc.wait()

    def get_status(self):
        exit_code = self.command_proc.poll()
        if exit_code is None:
            return "running"
        if exit_code == 0:
            return "finished"
        return "failed"


class LocalRunner(AbstractRunner):
    def run(self, project, backend_config):
        synchronous = backend_config[PROJECT_SYNCHRONOUS]
        docker_args = backend_config[PROJECT_DOCKER_ARGS]

        entry_point = project.get_single_entry_point()

        entry_cmd = entry_point.command
        copy_code = False
        if project.docker_env.get("image"):
            pull_docker_image(project.docker_env["image"])
            copy_code = True
        else:
            project.docker_env["image"] = generate_docker_image(project, entry_cmd)

        command_args = []
        command_separator = " "
        validate_docker_env(project)
        validate_docker_installation()
        image = build_docker_image(
            project=project,
            base_image=project.docker_env.get("image"),
            api=self._api,
            copy_code=copy_code,
        )
        command_args += get_docker_command(image=image, docker_args=docker_args,)
        if backend_config.get("runQueueItemId"):
            self._api.ack_run_queue_item(
                backend_config["runQueueItemId"], project.run_id
            )
        # In synchronous mode, run the entry point command in a blocking fashion, sending status
        # updates to the tracking server when finished. Note that the run state may not be
        # persisted to the tracking server if interrupted
        if synchronous:
            command_args += get_entry_point_command(
                project, entry_point, project.parameters
            )
            command_str = command_separator.join(command_args)

            print("Launching run in docker with command: {}".format(command_str))
            wandb.termlog(
                "Launching run in docker with command: {}".format(command_str)
            )
            run = _run_entry_point(command_str, project.dir)
            run.wait()
            return run
        # Otherwise, invoke `wandb launch` in a subprocess
        raise LaunchException("asynchrnous mode not yet available")


def _run_launch_cmd(cmd):
    """
    Invoke ``wandb launch`` in a subprocess, which in turn runs the entry point in a child process.
    Returns a handle to the subprocess. Popen launched to invoke ``wandb launch``.
    """
    final_env = os.environ.copy()
    # Launch `wandb launch` command as the leader of its own process group so that we can do a
    # best-effort cleanup of all its descendant processes if needed
    if sys.platform == "win32":
        return subprocess.Popen(
            cmd,
            env=final_env,
            universal_newlines=True,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    else:
        return subprocess.Popen(
            cmd, env=final_env, universal_newlines=True, preexec_fn=os.setsid
        )


def _run_entry_point(command, work_dir):
    """
    Run an entry point command in a subprocess, returning a SubmittedRun that can be used to
    query the run's status.
    :param command: Entry point command to run
    :param work_dir: Working directory in which to run the command
    :param run: SubmittedRun object associated with the entry point execution.
    """
    env = os.environ.copy()
    if os.name == "nt":
        # we are running on windows
        process = subprocess.Popen(
            ["cmd", "/c", command], close_fds=True, cwd=work_dir, env=env
        )
    else:
        process = subprocess.Popen(
            ["bash", "-c", command], close_fds=True, cwd=work_dir, env=env,
        )

    return LocalSubmittedRun(process)
