import logging
import os
import re
import signal
import subprocess
from typing import Any, Dict, List, Optional

import wandb
from wandb.errors import CommError, LaunchError

from .abstract import AbstractRun, AbstractRunner, Status
from .._project_spec import LaunchProject
from ..docker import (
    build_docker_image_if_needed,
    construct_local_image_uri,
    docker_image_exists,
    docker_image_inspect,
    generate_docker_base_image,
    get_full_command,
    pull_docker_image,
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
        _logger.info("Validating docker installation")
        validate_docker_installation()
        synchronous: bool = self.backend_config[PROJECT_SYNCHRONOUS]
        docker_args: Dict[str, Any] = self.backend_config[PROJECT_DOCKER_ARGS]
        entry_point = launch_project.get_single_entry_point()

        entry_cmd = entry_point.command
        copy_code = True
        if launch_project.docker_image:
            _logger.info("Pulling user provided docker image")
            pull_docker_image(launch_project.docker_image)
            copy_code = False
        else:
            # TODO: potentially pull the base_image
            if not docker_image_exists(launch_project.base_image):
                if generate_docker_base_image(launch_project, entry_cmd) is None:
                    raise LaunchError("Unable to build base image")
            else:
                wandb.termlog(
                    "Using existing base image: {}".format(launch_project.base_image)
                )

        command_separator = " "
        command_args = []

        _logger.info("Inspecting base image for env, and working dir...")
        container_inspect = docker_image_inspect(launch_project.base_image)
        container_workdir = container_inspect["ContainerConfig"].get("WorkingDir", "/")
        container_env: List[str] = container_inspect["ContainerConfig"]["Env"]
        if launch_project.docker_image is None or launch_project.build_image:
            image_uri = construct_local_image_uri(launch_project)
            command_args = get_full_command(
                image_uri,
                launch_project,
                self._api,
                container_workdir,
                docker_args,
                entry_point,
            )
            command_str = command_separator.join(command_args)

            sanitized_command_str = re.sub(
                r"WANDB_API_KEY=\w+", "WANDB_API_KEY", command_str
            )

            _logger.info("Building docker image...")
            build_docker_image_if_needed(
                launch_project=launch_project,
                api=self._api,
                copy_code=copy_code,
                workdir=container_workdir,
                container_env=container_env,
                runner_type="local",
                image_uri=image_uri,
                command_args=command_args,
            )
        else:
            # TODO: rewrite env vars and copy code in supplied docker image
            wandb.termwarn(
                "Using supplied docker image: {}. Artifact swapping and launch metadata disabled".format(
                    launch_project.docker_image
                )
            )
            image_uri = launch_project.docker_image
            _logger.info("Getting docker command...")
            command_args = get_full_command(
                image_uri,
                launch_project,
                self._api,
                container_workdir,
                docker_args,
                entry_point,
            )
            command_str = command_separator.join(command_args)

            sanitized_command_str = re.sub(
                r"WANDB_API_KEY=\w+", "WANDB_API_KEY", command_str
            )

        if self.backend_config.get("runQueueItemId"):
            try:
                _logger.info("Acking run queue item...")
                self._api.ack_run_queue_item(
                    self.backend_config["runQueueItemId"], launch_project.run_id
                )
            except CommError:
                wandb.termerror(
                    "Error acking run queue item. Item lease may have ended or another process may have acked it."
                )
                return None

        wandb.termlog(
            "Launching run in docker with command: {}".format(sanitized_command_str)
        )
        run = _run_entry_point(command_str, launch_project.project_dir)
        if synchronous:
            run.wait()
        return run


def _run_entry_point(command: str, work_dir: str) -> AbstractRun:
    """Run an entry point command in a subprocess.

    Arguments:
        command: Entry point command to run
        work_dir: Working directory in which to run the command

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
