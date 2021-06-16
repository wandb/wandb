from abc import ABC, abstractmethod
import logging
import os
import subprocess
import sys

from dockerpycreds.utils import find_executable  # type: ignore
import wandb
from wandb import Settings

_logger = logging.getLogger(__name__)

if wandb.TYPE_CHECKING:
    from typing import Dict


# TODO: is this ok?
if wandb.TYPE_CHECKING:
    from typing import Literal
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

    def __init__(self):
        self._status = Status()

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


class AbstractRunner(ABC):
    """
    Abstract plugin class defining the interface needed to execute W&B Launches. You can define
    subclasses of ``AbstractRunner`` and expose them as third-party plugins to enable running
    W&B projects against custom execution backends (e.g. to run projects against your team's
    in-house cluster or job scheduler).
    """

    def __init__(self, api):  # TODO: maybe don't want to pass api_key here...
        # self._config = config  #TODO:
        self._settings = Settings()
        self._api = api
        self._cwd = os.getcwd()
        self._namespace = wandb.util.generate_id()

    def find_executable(self, cmd):
        """Cross platform utility for checking if a program is available"""
        return find_executable(cmd)

    @property
    def api_key(self):
        return self._api.api_key

    def verify(self):
        """This is called on first boot to verify the needed commands,
        and permissions are available.

        For now just call `wandb.termerror` and `sys.exit(1)`
        """
        if self._api.api_key is None:
            wandb.termerror(
                "Couldn't find W&B api key, run wandb login or set WANDB_API_KEY"
            )
            sys.exit(1)
        return True

    @abstractmethod
    def run(self, project, backend_config):
        """
        Submit an entrypoint. It must return a SubmittedRun object to track the execution
        :param project_uri: URI of the project to execute, e.g. a local filesystem path
               or a Git repository URI like https://github.com/wandb/examples
        :param entry_point: Entry point to run within the project.
        :param params: Dict of parameters to pass to the entry point
        :param version: For git-based projects, either a commit hash or a branch name.
        :param backend_config: A dictionary, or a path to a JSON file (must end in '.json'), which
                               will be passed as config to the backend. The exact content which
                               should be provided is different for each execution backend.
        :return: A :py:class:`wandb.sdk.launch.runners.SubmittedRun`. This function is expected to run
                 the project asynchronously, i.e. it should trigger project execution and then
                 immediately return a `SubmittedRun` to track execution status.
        """
        pass
