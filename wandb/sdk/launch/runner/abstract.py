"""Implementation of the abstract runner class.

This class defines the interface that the W&B launch runner uses to manage the lifecycle
of runs launched in different environments (e.g. runs launched locally or in a cluster).
"""

import logging
import os
import shutil
import subprocess
import sys
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Literal, Optional, Union

import wandb
from wandb.apis.internal import Api
from wandb.sdk.lib import runid

from .._project_spec import LaunchProject

_logger = logging.getLogger(__name__)


State = Literal[
    "unknown",
    "starting",
    "running",
    "failed",
    "finished",
    "stopping",
    "stopped",
    "preempted",
]


class Status:
    def __init__(self, state: "State" = "unknown", messages: List[str] = None):  # type: ignore
        self.state = state
        self.messages = messages or []

    def __repr__(self) -> "State":
        return self.state

    def __str__(self) -> str:
        return self.state

    def __eq__(self, __value: object) -> bool:
        if isinstance(__value, Status):
            return self.state == __value.state
        else:
            return self.state == __value

    def __hash__(self) -> int:
        return hash(self.state)


class AbstractRun(ABC):
    """Wrapper around a W&B launch run.

    A launched run is a subprocess running an entry point
    command, that exposes methods for waiting on and cancelling the run.
    This class defines the interface that the W&B launch runner uses to manage the lifecycle
    of runs launched in different environments (e.g. runs launched locally or in a cluster).
    ``AbstractRun`` is not thread-safe. That is, concurrent calls to wait() / cancel()
    from multiple threads may inadvertently kill resources (e.g. local processes) unrelated to the
    run.
    """

    def __init__(self) -> None:
        self._status = Status()

    @property
    def status(self) -> Status:
        return self._status

    @abstractmethod
    async def get_logs(self) -> Optional[str]:
        """Return the logs associated with the run."""

    def _run_cmd(
        self, cmd: List[str], output_only: Optional[bool] = False
    ) -> Optional[Union["subprocess.Popen[bytes]", bytes]]:
        """Run the command and returns a popen object or the stdout of the command.

        Arguments:
        cmd: The command to run
        output_only: If true just return the stdout bytes
        """
        try:
            env = os.environ
            popen = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE)
            if output_only:
                popen.wait()
                if popen.stdout is not None:
                    return popen.stdout.read()
            return popen
        except subprocess.CalledProcessError as e:
            wandb.termerror(f"Command failed: {e}")
            return None

    @abstractmethod
    async def wait(self) -> bool:
        """Wait for the run to finish, returning True if the run succeeded and false otherwise.

        Note that in some cases, we may wait until the remote job completes rather than until the W&B run completes.
        """

    @abstractmethod
    async def get_status(self) -> Status:
        """Get status of the run."""

    @abstractmethod
    async def cancel(self) -> None:
        """Cancel the run (interrupts the command subprocess, cancels the run, etc).

        Cancels the run and waits for it to terminate. The W&B run status may not be
        set correctly upon run cancellation.
        """

    @property
    @abstractmethod
    def id(self) -> Optional[str]:
        pass


class AbstractRunner(ABC):
    """Abstract plugin class defining the interface needed to execute W&B Launches.

    You can define subclasses of ``AbstractRunner`` and expose them as third-party
    plugins to enable running W&B projects against custom execution backends
    (e.g. to run projects against your team's in-house cluster or job scheduler).
    """

    _type: str

    def __init__(
        self,
        api: Api,
        backend_config: Dict[str, Any],
    ) -> None:
        self._api = api
        self.backend_config = backend_config
        self._cwd = os.getcwd()
        self._namespace = runid.generate_id()

    def find_executable(
        self,
        cmd: str,
    ) -> Union[str, None]:
        """Cross platform utility for checking if a program is available."""
        return shutil.which(cmd)

    @property
    def api_key(self) -> Any:
        return self._api.api_key

    def verify(self) -> bool:
        """This is called on first boot to verify the needed commands, and permissions are available.

        For now just call `wandb.termerror` and `sys.exit(1)`
        """
        if self._api.api_key is None:
            wandb.termerror(
                "Couldn't find W&B api key, run wandb login or set WANDB_API_KEY"
            )
            sys.exit(1)
        return True

    @abstractmethod
    async def run(
        self,
        launch_project: LaunchProject,
        image_uri: str,
    ) -> Optional[AbstractRun]:
        """Submit an LaunchProject to be run.

        Returns a SubmittedRun object to track the execution
        Arguments:
        launch_project: Object of _project_spec.LaunchProject class representing a wandb launch project

        Returns:
            A :py:class:`wandb.sdk.launch.runners.SubmittedRun`. This function is expected to run
            the project asynchronously, i.e. it should trigger project execution and then
            immediately return a `SubmittedRun` to track execution status.
        """
