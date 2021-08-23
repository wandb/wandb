import logging
import os
import signal
import subprocess
import sys
from typing import Any, Dict, List, Optional

import wandb
from wandb.errors import CommError, LaunchError

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
    """Instance of ``AbstractRun`` corresponding to a subprocess launched to run an entry point command locally."""

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
    """Runner class, uses a project to create a LocallySubmittedRun."""

    def run(self, launch_project: LaunchProject) -> Optional[AbstractRun]:
        synchronous: bool = self.backend_config[PROJECT_SYNCHRONOUS]
        docker_args: Dict[str, Any] = self.backend_config[PROJECT_DOCKER_ARGS]

        entry_point = launch_project.get_single_entry_point()

        entry_cmd = entry_point.command
        copy_code = False
        if launch_project.docker_image:
            pull_docker_image(launch_project.docker_image)
            copy_code = True
        else:
            launch_project.docker_image = generate_docker_image(
                launch_project, entry_cmd
            )

        command_args = []
        command_separator = " "
        validate_docker_env(launch_project)
        validate_docker_installation()
        image = build_docker_image(
            launch_project=launch_project,
            base_image=launch_project.docker_image,
            copy_code=copy_code,
        )
        command_args += get_docker_command(
            image=image,
            launch_project=launch_project,
            api=self._api,
            docker_args=docker_args,
        )
        if self.backend_config.get("runQueueItemId"):
            try:
                self._api.ack_run_queue_item(
                    self.backend_config["runQueueItemId"], launch_project.run_id
                )
            except CommError:
                wandb.termerror(
                    "Error acking run queue item. Item lease may have ended or another process may have acked it."
                )
                return None

        # In synchronous mode, run the entry point command in a blocking fashion, sending status
        # updates to the tracking server when finished. Note that the run state may not be
        # persisted to the tracking server if interrupted
        if synchronous:
            command_args += get_entry_point_command(
                entry_point, launch_project.override_args
            )
            command_str = command_separator.join(command_args)

            wandb.termlog(
                "Launching run in docker with command: {}".format(command_str)
            )
            run = _run_entry_point(command_str, launch_project.project_dir)
            run.wait()
            return run
        # Otherwise, invoke `wandb launch` in a subprocess
        raise LaunchError("asynchronous mode not yet available")


def _run_launch_cmd(cmd: List[str]) -> "subprocess.Popen[str]":
    """Invoke ``wandb launch`` in a subprocess, which in turn runs the entry point in a child process.

    Arguments:
    cmd: List of strings indicating the command to run

    Returns:
        A handle to the subprocess. Popen launched to invoke ``wandb launch``.
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
    """Run an entry point command in a subprocess.

    Arguments:
    command: Entry point command to run
    work_dir: Working directory in which to run the command
    run: SubmittedRun object associated with the entry point execution.

    Returns:
        An instance of `LocalSubmittedRun`
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
