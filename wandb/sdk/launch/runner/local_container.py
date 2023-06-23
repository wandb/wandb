import logging
import os
import shlex
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Optional

import wandb
from wandb.sdk.launch.agent.job_status_tracker import JobAndRunStatusTracker
from wandb.sdk.launch.builder.abstract import AbstractBuilder
from wandb.sdk.launch.environment.abstract import AbstractEnvironment

from .._project_spec import LaunchProject
from ..builder.build import get_env_vars_dict
from ..utils import (
    LOG_PREFIX,
    PROJECT_SYNCHRONOUS,
    _is_wandb_dev_uri,
    _is_wandb_local_uri,
    pull_docker_image,
    sanitize_wandb_api_key,
)
from .abstract import AbstractRun, AbstractRunner, Status

_logger = logging.getLogger(__name__)


class LocalSubmittedRun(AbstractRun):
    """Instance of ``AbstractRun`` corresponding to a subprocess launched to run an entry point command locally."""

    def __init__(self) -> None:
        super().__init__()
        self._command_proc: Optional[subprocess.Popen] = None
        self._stdout: Optional[str] = None
        self._terminate_flag: bool = False
        self._thread: Optional[threading.Thread] = None

    def set_command_proc(self, command_proc: subprocess.Popen) -> None:
        self._command_proc = command_proc

    def set_thread(self, thread: threading.Thread) -> None:
        self._thread = thread

    @property
    def id(self) -> Optional[str]:
        if self._command_proc is None:
            return None
        return str(self._command_proc.pid)

    def wait(self) -> bool:
        assert self._thread is not None
        # if command proc is not set
        # wait for thread to set it
        if self._command_proc is None:
            while self._thread.is_alive():
                time.sleep(5)
                # command proc can be updated by another thread
                if self._command_proc is not None:
                    return self._command_proc.wait() == 0  # type: ignore
            return False

        return self._command_proc.wait() == 0

    def get_logs(self) -> Optional[str]:
        return self._stdout

    def cancel(self) -> None:
        # thread is set immediately after starting, should always exist
        assert self._thread is not None

        # cancel called before the thread subprocess has started
        # indicates to thread to not start command proc if not already started
        self._terminate_flag = True

    def get_status(self) -> Status:
        assert self._thread is not None, "Failed to get status, self._thread = None"
        if self._command_proc is None:
            if self._thread.is_alive():
                return Status("running")
            return Status("stopped")
        exit_code = self._command_proc.poll()
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

    def _populate_docker_args(self, launch_project: LaunchProject) -> Dict[str, Any]:
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

        return docker_args

    def run(
        self,
        launch_project: LaunchProject,
        builder: Optional[AbstractBuilder],
        job_tracker: Optional[JobAndRunStatusTracker] = None,
    ) -> Optional[AbstractRun]:
        docker_args = self._populate_docker_args(launch_project)
        synchronous: bool = self.backend_config[PROJECT_SYNCHRONOUS]
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
            env_vars["WANDB_BASE_URL"] = "http://host.docker.internal:9001"

        if launch_project.docker_image:
            # user has provided their own docker image
            image_uri = launch_project.image_name
            pull_docker_image(image_uri)
            entry_cmd = []
            if entry_point is not None:
                entry_cmd = entry_point.command
            command_str = " ".join(
                get_docker_command(
                    image_uri,
                    env_vars,
                    entry_cmd=entry_cmd,
                    docker_args=docker_args,
                    additional_args=launch_project.override_args,
                )
            ).strip()
        else:
            assert entry_point is not None
            _logger.info("Building docker image...")
            assert builder is not None
            image_uri = builder.build_image(launch_project, entry_point, job_tracker)
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
        launch_project.fill_macros(image_uri)
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
    run = LocalSubmittedRun()
    thread = threading.Thread(
        target=_thread_process_runner,
        args=(run, ["bash", "-c", command], work_dir, env),
    )
    run.set_thread(thread)
    thread.start()
    return run


def _thread_process_runner(
    run: LocalSubmittedRun, args: List[str], work_dir: str, env: Dict[str, str]
) -> None:
    # cancel was called before we started the subprocess
    if run._terminate_flag:
        return
    process = subprocess.Popen(
        args,
        close_fds=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        bufsize=1,
        cwd=work_dir,
        env=env,
    )
    run.set_command_proc(process)
    run._stdout = ""
    while True:
        # the agent thread could set the terminate flag
        if run._terminate_flag:
            process.terminate()  # type: ignore
        chunk = os.read(process.stdout.fileno(), 4096)  # type: ignore
        if not chunk:
            break
        index = chunk.find(b"\r")
        decoded_chunk = chunk.decode()
        if index != -1:
            run._stdout += decoded_chunk
            print(chunk.decode(), end="")
        else:
            run._stdout += decoded_chunk + "\r"
            print(chunk.decode(), end="\r")


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
