from abc import ABC, abstractmethod
import logging
import os
import subprocess
import sys

from dockerpycreds.utils import find_executable
import wandb
from wandb import Settings

from ..utils import fetch_and_validate_project, load_project

_logger = logging.getLogger(__name__)

if wandb.TYPE_CHECKING:
    from typing import Dict


# TODO: is this ok?
try:
    from typing import Literal
except ImportError:
    from typing_extensions import Literal


State = Literal["unknown", "starting", "running", "failed", "finished"]


class Status(object):
    def __init__(self, state: State = "unknown", data=None):
        self.state = state
        self.data = data or {}

    def __repr__(self):
        return self.state


class AbstractRun(ABC):
    """
    Wrapper around a W&B launch run (e.g. a subprocess running an entry point
    command) and exposing methods for waiting on and cancelling the run.
    This class defines the interface that the W&B launch runner uses to manage the lifecycle
    of runs launched in different environments (e.g. runs launched locally or in a cluster).
    ``AbstractRun`` is not thread-safe. That is, concurrent calls to wait() / cancel()
    from multiple threads may inadvertently kill resources (e.g. local processes) unrelated to the
    run.
    """

    STATE_MAP: Dict[str, State] = {}

    def __init__(self, run_id: str):
        self._run_id = run_id
        self._status = Status()

    @property
    def run_id(self):
        # TODO: not sure if we want this..
        return self._run_id

    @property
    def status(self):
        return self._status

    def _run_cmd(self, cmd, output_only=False):
        """Runs the command and returns a popen object or the stdout of the command

        Arguments:
            cmd (List[str]): The command to run
            output_only (Optional(bool)): If true just return the stdout bytes
        """

        try:
            env = os.environ
            popen = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE)
            if output_only:
                popen.wait()
                return popen.stdout.read()
            return popen
        except subprocess.CalledProcessError as e:
            wandb.termerror("Command failed: {}".format(e))
            return None

    @abstractmethod
    def wait(self):
        """
        Wait for the run to finish, returning True if the run succeeded and false otherwise. Note
        that in some cases, we may wait until the remote job
        completes rather than until the W&B run completes.
        """
        pass

    @abstractmethod
    def get_status(self):
        """
        Get status of the run.
        """
        pass

    @abstractmethod
    def cancel(self):
        """
        Cancel the run (interrupts the command subprocess, cancels the run, etc) and
        waits for it to terminate. The W&B run status may not be set correctly
        upon run cancellation.
        """
        pass

    @property
    @abstractmethod
    def id(self):
        pass


class AbstractBackend(ABC):
    """
    Abstract plugin class defining the interface needed to execute W&B Launches. You can define
    subclasses of ``AbstractBackend`` and expose them as third-party plugins to enable running
    MLflow projects against custom execution backends (e.g. to run projects against your team's
    in-house cluster or job scheduler).
    """

    def __init__(self, api_key=None):  # TODO: maybe don't want to pass api_key here...
        # self._config = config  #TODO:
        self._settings = Settings()
        self._api_key = api_key
        self._cwd = os.getcwd()
        self._namespace = wandb.util.generate_id()

    def fetch_and_validate_project(self, project_uri, version, entry_point, params):
        return load_project(
            fetch_and_validate_project(project_uri, version, entry_point, params)
        )

    def find_executable(self, cmd):
        """Cross platform utility for checking if a program is available"""
        return find_executable(cmd)

    @property
    def api_key(self):
        return self._api_key

    def verify(self):
        """This is called on first boot to verify the needed commands,
        and permissions are available.

        For now just call `wandb.termerror` and `sys.exit(1)`
        """
        if self._api_key is None:
            wandb.termerror(
                "Couldn't find W&B api key, run wandb login or set WANDB_API_KEY"
            )
            sys.exit(1)
        return True

    @abstractmethod
    def run(
        self, project_uri, entry_point, params, version, backend_config, experiment_id
    ):
        """
        Submit an entrypoint. It must return a SubmittedRun object to track the execution
        :param project_uri: URI of the project to execute, e.g. a local filesystem path
               or a Git repository URI like https://github.com/mlflow/mlflow-example
        :param entry_point: Entry point to run within the project.
        :param params: Dict of parameters to pass to the entry point
        :param version: For git-based projects, either a commit hash or a branch name.
        :param backend_config: A dictionary, or a path to a JSON file (must end in '.json'), which
                               will be passed as config to the backend. The exact content which
                               should be provided is different for each execution backend and is
                               documented at https://www.mlflow.org/docs/latest/projects.html.
        :param experiment_id: ID of experiment under which to launch the run.
        :return: A :py:class:`wandb.sdk.launch.backends.SubmittedRun`. This function is expected to run
                 the project asynchronously, i.e. it should trigger project execution and then
                 immediately return a `SubmittedRun` to track execution status.
        """
        pass
