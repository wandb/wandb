from abc import abstractmethod
import os
import subprocess
import time

from dockerpycreds.utils import find_executable
import wandb
from wandb import Settings
from wandb.compat import tempfile
from wandb.apis import internal_runqueue

if wandb.TYPE_CHECKING:
    from typing import Dict

# TODO: is this ok?
try:
    from typing import Literal
except ImportError:
    from typing_extensions import Literal


State = Literal["starting", "running", "failed", "finished"]


class Status(object):
    def __init__(self, state: State = "starting", data={}):
        self.state = state
        self.data = data

    def __repr__(self):
        return self.state


class BaseAgent(object):
    STATE_MAP: Dict[str, State] = {}
    REMOTE = True

    def __init__(self, entity: str, project: str, max: int = 4, queue: str = None):
        self._entity = entity
        self._project = project
        self._max = max
        self._api = internal_runqueue.Api()
        self._settings = Settings()
        self._jobs: Dict[str, Status] = {}
        self._ticks = 0
        self._running = 0
        self._cwd = os.getcwd()
        self._tmp_dir = tempfile.TemporaryDirectory()
        self._namespace = wandb.util.generate_id()
        self._queue = queue or "asdf"

    @property
    def api_key(self):
        return self._api.api_key

    @property
    def git(self):
        return self._api.git

    @property
    def job_ids(self):
        return list(self._jobs.keys())

    def stage(self, spec):
        staging_cfg = spec.get("staging_config", {})
        git_cfg = staging_cfg.get("git", {})
        if staging_cfg.get("code_artifact"):
            return staging_cfg["code_artifact"]
        elif self.git.enabled:
            commit = "HEAD"
            staging_dir = os.path.join(self._tmp_dir.name, wandb.util.generate_id())
            wandb.util.mkdir_exists_ok(staging_dir)
            if git_cfg.get("commit"):
                # TODO: share this logic with wandb restore?
                subprocess.check_call(["git", "fetch", "--all"])
                try:
                    self.git.repo.commit(git_cfg["commit"])
                    commit = git_cfg["commit"]
                except ValueError:
                    wandb.termwarn("Unable to find commit {} in this repository".format(git_cfg["commit"]))
            # TODO: handle patch
            subprocess.check_call(["git", "--work-tree", staging_dir, "checkout", commit, "--", "."])
            return staging_dir

    def check_queue(self):
        try:
            ups = self._api.pop_from_run_queue(
                self._queue, entity=self._entity, project=self._project
            )
        except Exception as e:
            print("Exception...", e)
            return None
        return ups

    def print_status(self):
        meta = {}
        for job_id in self.job_ids:
            status = self._jobs[job_id].state
            meta.setdefault(status, 0)
            meta[status] += 1
        updates = ""
        for status, count in meta.items():
            updates += ", {}: {}".format(status, count)
        print(updates[2:])

    def finish_job_id(self, job_id):
        """Removes the job from our list for now"""
        # TODO:  keep logs or something for the finished jobs
        del self._jobs[job_id]
        self._running -= 1

    def _update_finished(self, job_id):
        """Check our status enum"""
        if self._jobs[job_id].state in ["failed", "finished"]:
            self.finish_job_id(job_id)

    def _run_cmd(self, cmd, output_only=False):
        """Runs the command and returns the parsed result.

        Arguments:
            cmd (List[str]): The command to run
            output_only (Optional(bool)): If true just return the stdout bytes
        """

        try:
            wandb.util.exec_cmd(cmd, env=os.environ)
            env = os.environ
            popen = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE)
            if output_only:
                popen.wait()
                return popen.stdout.read()
            return self._parse_cmd(popen)
        except subprocess.CalledProcessError as e:
            wandb.termerror("Command failed: {}".format(e))
            return None

    def run_job(self, job):
        # TODO: logger
        print("agent: got job", job)
        spec = job.get("runSpec", {})
        command = self._setup_cmd(spec)
        job_id = self._run_cmd(command)
        if job_id is not None:
            self._running += 1
            self._api.ack_run_queue_item(job["runQueueItemId"], job_id)

    def loop(self):
        try:
            while True:
                self._ticks += 1
                if self._running >= self._max:
                    job = None
                else:
                    job = self.check_queue()
                if not job:
                    time.sleep(30)
                    self._update_status()
                    for job_id in self.job_ids:
                        self._update_finished(job_id)
                    if self._ticks % 2 == 0:
                        self.print_status()
                    continue
                self.run_job(job)
        except KeyboardInterrupt:
            wandb.termlog("Shutting down, active jobs:")
            self.print_status()

    def find_executable(self, cmd):
        """Cross platform utility for checking if a program is available"""
        return find_executable(cmd)

    def verify(self):
        """This is called on first boot to verify the needed commands,
        and permissions are available.

        For now just call `wandb.termerror` and `sys.exit(1)`
        """
        return True

    @abstractmethod
    def _setup_cmd(self, spec):
        """This should prepare the agent for running a command.

        Arguments:
            spec (Dict[str]: Any): configuration details from the server, typing TBD

        Returns:
            command: List[str]
        """
        return NotImplementedError()

    @abstractmethod
    def _parse_cmd(self, popen):
        """This should wait for and parse the commands output.  It must set
        an id in the `self._jobs` dict to a dict with a "status" key

        Returns:
            job_id: str
        """
        raise NotImplementedError()

    @abstractmethod
    def _update_status(self):
        """This should iterate over the jobs and set their status key""" 
        raise NotImplementedError()
