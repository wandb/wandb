import logging
import os
import shlex
import signal
import subprocess
import sys
from typing import Any, Dict, List, Optional

import wandb
from wandb.sdk.launch.builder.abstract import AbstractBuilder
from wandb.sdk.launch.environment.abstract import AbstractEnvironment

from .._project_spec import LaunchProject, compute_command_args
from ..builder.build import get_env_vars_dict
from ..utils import (
    LOG_PREFIX,
    PROJECT_SYNCHRONOUS,
    _is_wandb_dev_uri,
    _is_wandb_local_uri,
    docker_image_exists,
    pull_docker_image,
    sanitize_wandb_api_key,
)
from .abstract import AbstractRun, AbstractRunner, Status

_logger = logging.getLogger(__name__)


class LocalSubmittedRun(AbstractRun):
    """Instance of ``AbstractRun`` corresponding to a subprocess launched to run an entry point command locally."""

    def __init__(self, command_proc: "subprocess.Popen[bytes]") -> None:
        super().__init__()
        self.command_proc = command_proc

    @property
    def id(self) -> str:
        return str(self.command_proc.pid)

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
                _msg = f"{LOG_PREFIX}Failed to terminate child process PID {self.command_proc.pid}"
                _logger.debug(_msg)
            self.command_proc.wait()

    def get_status(self) -> Status:
        exit_code = self.command_proc.poll()
        if exit_code is None:
            return Status("running")
        if exit_code == 0:
            return Status("finished")
        return Status("failed")


class LocalContainerRunner(AbstractRunner):
    """Runner class, uses a project to create a LocallySubmittedRun."""

    def __init__(
        self,
        api: wandb.apis.internal.Api,
        backend_config: Dict[str, Any],
        environment: AbstractEnvironment,
    ) -> None:
        super().__init__(api, backend_config)
        self.environment = environment

    def run(
        self,
        launch_project: LaunchProject,
        builder: Optional[AbstractBuilder],
    ) -> Optional[AbstractRun]:
        synchronous: bool = self.backend_config[PROJECT_SYNCHRONOUS]
        docker_args: Dict[str, Any] = launch_project.resource_args.get(
            "local-container", {}
        )

        if _is_wandb_local_uri(self._api.settings("base_url")):
            if sys.platform == "win32":
                docker_args["net"] = "host"
            else:
                docker_args["network"] = "host"
            if sys.platform == "linux" or sys.platform == "linux2":
                docker_args["add-host"] = "host.docker.internal:host-gateway"

        entry_point = launch_project.get_single_entry_point()
        env_vars = get_env_vars_dict(launch_project, self._api)

        # When running against local port, need to swap to local docker host
        if (
            _is_wandb_local_uri(self._api.settings("base_url"))
            and sys.platform == "darwin"
        ):
            _, _, port = self._api.settings("base_url").split(":")
            env_vars["WANDB_BASE_URL"] = f"http://host.docker.internal:{port}"
        elif _is_wandb_dev_uri(self._api.settings("base_url")):
            env_vars["WANDB_BASE_URL"] = "http://host.docker.internal:9002"

        if launch_project.docker_image:
            # user has provided their own docker image
            image_uri = launch_project.image_name
            if not docker_image_exists(image_uri):
                pull_docker_image(image_uri)
            entry_cmd = []
            if entry_point is not None:
                entry_cmd = entry_point.command
            override_args = compute_command_args(launch_project.override_args)
            command_str = " ".join(
                get_docker_command(
                    image_uri,
                    env_vars,
                    entry_cmd=entry_cmd,
                    docker_args=docker_args,
                    additional_args=override_args,
                )
            ).strip()
        else:
            assert entry_point is not None
            _logger.info("Building docker image...")
            assert builder is not None
            image_uri = builder.build_image(
                launch_project,
                entry_point,
            )
            _logger.info(f"Docker image built with uri {image_uri}")
            # entry_cmd and additional_args are empty here because
            # if launch built the container they've been accounted
            # in the dockerfile and env vars respectively
            command_str = " ".join(
                get_docker_command(
                    image_uri,
                    env_vars,
                    docker_args=docker_args,
                )
            ).strip()

        sanitized_cmd_str = sanitize_wandb_api_key(command_str)
        _msg = f"{LOG_PREFIX}Launching run in docker with command: {sanitized_cmd_str}"
        wandb.termlog(_msg)
        run = _run_entry_point(command_str, launch_project.project_dir)
        if synchronous:
            run.wait()
        return run


def _run_entry_point(command: str, work_dir: Optional[str]) -> AbstractRun:
    """Run an entry point command in a subprocess.

    Arguments:
        command: Entry point command to run
        work_dir: Working directory in which to run the command

    Returns:
        An instance of `LocalSubmittedRun`
    """
    if work_dir is None:
        work_dir = os.getcwd()
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


def get_docker_command(
    image: str,
    env_vars: Dict[str, str],
    entry_cmd: Optional[List[str]] = None,
    docker_args: Optional[Dict[str, Any]] = None,
    additional_args: Optional[List[str]] = None,
) -> List[str]:
    """Construct the docker command using the image and docker args.

    Arguments:
    image: a Docker image to be run
    env_vars: a dictionary of environment variables for the command
    entry_cmd: the entry point command to run
    docker_args: a dictionary of additional docker args for the command
    """
    docker_path = "docker"
    cmd: List[Any] = [docker_path, "run", "--rm"]

    # hacky handling of env vars, needs to be improved
    for env_key, env_value in env_vars.items():
        cmd += ["-e", f"{shlex.quote(env_key)}={shlex.quote(env_value)}"]

    if docker_args:
        for name, value in docker_args.items():
            if len(name) == 1:
                prefix = "-" + shlex.quote(name)
            else:
                prefix = "--" + shlex.quote(name)
            if isinstance(value, list):
                for v in value:
                    cmd += [prefix, shlex.quote(str(v))]
            elif isinstance(value, bool) and value:
                cmd += [prefix]
            else:
                cmd += [prefix, shlex.quote(str(value))]

    if entry_cmd:
        cmd += ["--entrypoint", entry_cmd[0]]
    cmd += [shlex.quote(image)]
    if entry_cmd and len(entry_cmd) > 1:
        cmd += entry_cmd[1:]
    if additional_args:
        cmd += additional_args
    return cmd


def join(split_command: List[str]) -> str:
    """Return a shell-escaped string from *split_command*."""
    return " ".join(shlex.quote(arg) for arg in split_command)
