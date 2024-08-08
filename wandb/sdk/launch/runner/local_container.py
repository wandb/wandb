import asyncio
import logging
import os
import shlex
import subprocess
import sys
import threading
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import wandb
from wandb.sdk.launch.environment.abstract import AbstractEnvironment
from wandb.sdk.launch.registry.abstract import AbstractRegistry

from .._project_spec import LaunchProject
from ..errors import LaunchError
from ..utils import (
    CODE_MOUNT_DIR,
    LOG_PREFIX,
    MAX_ENV_LENGTHS,
    PROJECT_SYNCHRONOUS,
    _is_wandb_dev_uri,
    _is_wandb_local_uri,
    docker_image_exists,
    event_loop_thread_exec,
    pull_docker_image,
    sanitize_wandb_api_key,
)
from .abstract import AbstractRun, AbstractRunner, Status

if TYPE_CHECKING:
    from wandb.apis.internal import Api

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

    async def wait(self) -> bool:
        assert self._thread is not None
        # if command proc is not set
        # wait for thread to set it
        if self._command_proc is None:
            while self._thread.is_alive():
                await asyncio.sleep(5)
                # command proc can be updated by another thread
                if self._command_proc is not None:
                    break  # type: ignore  # mypy thinks this is unreachable
            else:
                return False
        wait = event_loop_thread_exec(self._command_proc.wait)
        return int(await wait()) == 0

    async def get_logs(self) -> Optional[str]:
        return self._stdout

    async def cancel(self) -> None:
        # thread is set immediately after starting, should always exist
        assert self._thread is not None

        # cancel called before the thread subprocess has started
        # indicates to thread to not start command proc if not already started
        self._terminate_flag = True

    async def get_status(self) -> Status:
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
        api: "Api",
        backend_config: Dict[str, Any],
        environment: AbstractEnvironment,
        registry: AbstractRegistry,
    ) -> None:
        super().__init__(api, backend_config)
        self.environment = environment
        self.registry = registry

    def _populate_docker_args(
        self, launch_project: LaunchProject, image_uri: str
    ) -> Dict[str, Any]:
        docker_args: Dict[str, Any] = launch_project.fill_macros(image_uri).get(
            "local-container", {}
        )
        if _is_wandb_local_uri(self._api.settings("base_url")):
            if sys.platform == "win32":
                docker_args["net"] = "host"
            else:
                docker_args["network"] = "host"
            if sys.platform == "linux" or sys.platform == "linux2":
                docker_args["add-host"] = "host.docker.internal:host-gateway"
        base_image = launch_project.job_base_image
        if base_image is not None:
            # Mount code into the container and set the working directory.
            if "volume" not in docker_args:
                docker_args["volume"] = []
            docker_args["volume"].append(
                f"{launch_project.project_dir}:{CODE_MOUNT_DIR}"
            )
            docker_args["workdir"] = CODE_MOUNT_DIR
        return docker_args

    async def run(
        self,
        launch_project: LaunchProject,
        image_uri: str,
    ) -> Optional[AbstractRun]:
        docker_args = self._populate_docker_args(launch_project, image_uri)
        synchronous: bool = self.backend_config[PROJECT_SYNCHRONOUS]

        env_vars = launch_project.get_env_vars_dict(
            self._api, MAX_ENV_LENGTHS[self.__class__.__name__]
        )

        # When running against local port, need to swap to local docker host
        if (
            _is_wandb_local_uri(self._api.settings("base_url"))
            and sys.platform == "darwin"
        ):
            _, _, port = self._api.settings("base_url").split(":")
            env_vars["WANDB_BASE_URL"] = f"http://host.docker.internal:{port}"
        elif _is_wandb_dev_uri(self._api.settings("base_url")):
            env_vars["WANDB_BASE_URL"] = "http://host.docker.internal:9001"

        if launch_project.docker_image or launch_project.job_base_image:
            try:
                pull_docker_image(image_uri)
            except Exception as e:
                wandb.termwarn(f"Error attempting to pull docker image {image_uri}")
                if not docker_image_exists(image_uri):
                    raise LaunchError(
                        f"Failed to pull docker image {image_uri} with error: {e}"
                    )

        entrypoint = launch_project.get_job_entry_point()
        entry_cmd = None if entrypoint is None else entrypoint.command
        command_str = " ".join(
            get_docker_command(
                image_uri,
                env_vars,
                docker_args=docker_args,
                entry_cmd=entry_cmd,
                additional_args=launch_project.override_args,
            )
        ).strip()
        sanitized_cmd_str = sanitize_wandb_api_key(command_str)
        _msg = f"{LOG_PREFIX}Launching run in docker with command: {sanitized_cmd_str}"
        wandb.termlog(_msg)
        run = _run_entry_point(command_str, launch_project.project_dir)
        if synchronous:
            await run.wait()
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
    # TODO: Make this async
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
        decoded_chunk = None
        while not decoded_chunk:
            try:
                decoded_chunk = chunk.decode()
            except UnicodeDecodeError:
                # Multi-byte character cut off, try to get the rest of it
                chunk += os.read(process.stdout.fileno(), 1)  # type: ignore
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
