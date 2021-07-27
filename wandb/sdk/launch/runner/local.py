import logging
import os
import signal
import subprocess
import sys
from typing import Any, Dict, List

import wandb
from wandb.errors import LaunchException

from .abstract import AbstractRun, AbstractRunner, Status
from .._project_spec import get_entry_point_command, LaunchProject
from ..docker import (
    build_docker_image,
    generate_docker_image,
    get_docker_command,
    pull_docker_image,
    validate_docker_env,
    validate_docker_installation,
)
from ..utils import (
    PROJECT_DOCKER_ARGS,
    PROJECT_SYNCHRONOUS,
)


_logger = logging.getLogger(__name__)


class LocalSubmittedRun(AbstractRun):
    """
    Instance of ``AbstractRun`` corresponding to a subprocess launched to run an entry point
    command locally.
    """

    def __init__(self, command_proc: "subprocess.Popen[bytes]") -> None:
        super().__init__()
        self.command_proc = command_proc

    @property
    def id(self) -> int:
        return self.command_proc.pid

    def wait(self) -> bool:
        return self.command_proc.wait() == 0

    def cancel(self) -> None:
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

    def get_status(self) -> Status:
        exit_code = self.command_proc.poll()
        if exit_code is None:
            return Status("running")
        if exit_code == 0:
            return Status("finished")
        return Status("failed")


class LocalRunner(AbstractRunner):
    """Runner class, uses a project to create a LocallySubmittedRun"""

    def run(self, project: LaunchProject) -> AbstractRun:
        synchronous: bool = self.backend_config[PROJECT_SYNCHRONOUS]
        docker_args: Dict[str, Any] = self.backend_config[PROJECT_DOCKER_ARGS]

        entry_point = project.get_single_entry_point()

        entry_cmd = entry_point.command
        copy_code = False
        if project.docker_image:
            pull_docker_image(project.docker_image)
            copy_code = True
        else:
            project.docker_image = generate_docker_image(project, entry_cmd)

        command_args = []
        command_separator = " "
        validate_docker_env(project)
        validate_docker_installation()
        image = build_docker_image(
            project=project,
            base_image=project.docker_image,
            api=self._api,
            copy_code=copy_code,
        )
        command_args += get_docker_command(
            image=image,
            docker_args=docker_args,
        )
        if self.backend_config.get("runQueueItemId"):
            self._api.ack_run_queue_item(
                self.backend_config["runQueueItemId"], project.run_id
            )
        # In synchronous mode, run the entry point command in a blocking fashion, sending status
        # updates to the tracking server when finished. Note that the run state may not be
        # persisted to the tracking server if interrupted
        if synchronous:
            command_args += get_entry_point_command(entry_point, project.override_args)
            command_str = command_separator.join(command_args)

            wandb.termlog(
                "Launching run in docker with command: {}".format(command_str)
            )
            run = _run_entry_point(command_str, project.project_dir)
            run.wait()
            return run
        # Otherwise, invoke `wandb launch` in a subprocess
        raise LaunchException("asynchronous mode not yet available")


def _run_launch_cmd(cmd: List[str]) -> "subprocess.Popen[str]":
    """
    Invoke ``wandb launch`` in a subprocess, which in turn runs the entry point in a child process.
    Returns a handle to the subprocess. Popen launched to invoke ``wandb launch``.
    :param cmd: List of strings indicating command to run
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


def _run_entry_point(command: str, work_dir: str) -> AbstractRun:
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
            ["bash", "-c", command],
            close_fds=True,
            cwd=work_dir,
            env=env,
        )

    return LocalSubmittedRun(process)
