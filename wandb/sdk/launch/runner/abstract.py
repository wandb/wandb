"""Implementation of the abstract runner class.

This class defines the interface that the W&B launch runner uses to manage the lifecycle
of runs launched in different environments (e.g. runs launched locally or in a cluster).
"""
import json
import logging
import os
import re
import subprocess
import sys
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Union

from dockerpycreds.utils import find_executable  # type: ignore

import wandb
from wandb import Settings
from wandb.apis.internal import Api
from wandb.sdk.launch.builder.abstract import AbstractBuilder
from wandb.sdk.lib import runid

from .._project_spec import LaunchProject

_logger = logging.getLogger(__name__)


if sys.version_info >= (3, 8):
    from typing import Literal
else:
    from typing_extensions import Literal

State = Literal[
    "unknown", "starting", "running", "failed", "finished", "stopping", "stopped"
]

MACRO_REGEX = re.compile(r"\$\{(\w+)\}")


class Status:
    def __init__(self, state: "State" = "unknown", data=None):  # type: ignore
        self.state = state
        self.data = data or {}

    def __repr__(self) -> "State":
        return self.state


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
    def wait(self) -> bool:
        """Wait for the run to finish, returning True if the run succeeded and false otherwise.

        Note that in some cases, we may wait until the remote job completes rather than until the W&B run completes.
        """
        pass

    @abstractmethod
    def get_status(self) -> Status:
        """Get status of the run."""
        pass

    @abstractmethod
    def cancel(self) -> None:
        """Cancel the run (interrupts the command subprocess, cancels the run, etc).

        Cancels the run and waits for it to terminate. The W&B run status may not be
        set correctly upon run cancellation.
        """
        pass

    @property
    @abstractmethod
    def id(self) -> str:
        pass


class AbstractRunner(ABC):
    """Abstract plugin class defining the interface needed to execute W&B Launches.

    You can define subclasses of ``AbstractRunner`` and expose them as third-party
    plugins to enable running W&B projects against custom execution backends
    (e.g. to run projects against your team's in-house cluster or job scheduler).
    """

    def __init__(self, api: Api, backend_config: Dict[str, Any]) -> None:
        self._settings = Settings()
        self._api = api
        self.backend_config = backend_config
        self._cwd = os.getcwd()
        self._namespace = runid.generate_id()

    def find_executable(
        self, cmd: str
    ) -> Any:  # should return a string, but mypy doesn't trust find_executable
        """Cross platform utility for checking if a program is available."""
        return find_executable(cmd)

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

    def _fill_macros(self, project: LaunchProject, image: str) -> None:
        """Substitutes macros in the resource args of the given launch project.

        Certain macros can be used in resource args. These macros allow the
        user to set resource args dynamically in the context of the
        run being launched. The macros are given in the ${macro} format. The
        following macros are currently supported:

        ${wandb_project} - the name of the project the run is being launched to.
        ${wandb_entity} - the owner of the project the run being launched to.
        ${wandb_run_id} - the id of the run being launched
        ${wandb_run_name} - the name of the run being launched
        ${wandb_image} - the URI of the docker image being launched for this run

        Additionally, you may use ${<ENV-VAR-NAME>} to refer to the value of any
        environment variables that you plan to set in the environment of any
        agents that will receive these resource args.
        """
        update_dict = {
            "wandb_project": project.target_project,
            "wandb_entity": project.target_entity,
            "wandb_run_id": project.run_id,
            "wandb_run_name": project.run_name,
            "wandb_image": image,
        }
        update_dict.update(os.environ)
        config = json.dumps(project.resource_args)
        subbed = MACRO_REGEX.sub(
            lambda match: update_dict.get(match.group(1), match.group(0)), config
        )
        return json.loads(subbed)

    @abstractmethod
    def run(
        self,
        launch_project: LaunchProject,
        builder: AbstractBuilder,
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
        pass
