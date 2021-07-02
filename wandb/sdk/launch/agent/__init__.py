import os
import time

import wandb
from wandb import Settings
from wandb.errors import LaunchException


from ..runner.abstract import AbstractRun, State
from ..runner.loader import load_backend
from ..utils import (
    _collect_args,
    _convert_access,
    _is_wandb_local_uri,
    fetch_and_validate_project,
    PROJECT_DOCKER_ARGS,
)
from ...internal.internal_api import Api

if wandb.TYPE_CHECKING:
    from typing import Dict, Iterable


class LaunchAgent(object):
    STATE_MAP: Dict[str, State] = {}

    def __init__(self, entity: str, project: str, queues: Iterable[str] = None):
        self._entity = entity
        self._project = project
        self._max = max
        self._api = Api()
        self._settings = Settings()
        self._base_url = self._api.settings().get("base_url")
        self._jobs: Dict[str, AbstractRun] = {}
        self._ticks = 0
        self._running = 0
        self._cwd = os.getcwd()
        self._namespace = wandb.util.generate_id()
        self._access = _convert_access("project")
        self._queues: Iterable[Dict[str, str]] = []
        self._backend = (
            None  # todo: probably rename to runner to avoid confusion w cli backend
        )
        self.setup_run_queues(queues)

    def setup_run_queues(self, queues):
        project_run_queues = self._api.get_project_run_queues(
            self._entity, self._project
        )
        existing_run_queue_names = set(
            [run_queue["name"] for run_queue in project_run_queues]
        )
        if queues is None:
            for queue in project_run_queues:
                if queue["name"] == "default":
                    self._queues = ["default"]
                    return
            raise LaunchException(
                "Error launching launch-agent: Requested default queue for {}/{} but default queue does not exist.".format(
                    self._entity, self._project
                )
            )
        else:
            for queue in queues:
                if queue not in existing_run_queue_names:
                    raise LaunchException(
                        "Error launching launch-agent: {} does not exist for {}/{}".format(
                            queue, self._entity, self._project
                        )
                    )
                self._queues.append(queue)

    @property
    def job_ids(self):
        return list(self._jobs.keys())

    def verify(self):
        return self._backend.verify()

    def pop_from_queue(self, queue):
        try:
            ups = self._api.pop_from_run_queue(
                queue, entity=self._entity, project=self._project
            )
        except Exception as e:
            print("Exception:", e)
            return None
        return ups

    def print_status(self):
        print(
            "polling on project {}, queues {} for jobs".format(
                self._project, " ".join(self._queues)
            )
        )

    def finish_job_id(self, job_id):
        """Removes the job from our list for now"""
        # TODO:  keep logs or something for the finished jobs
        del self._jobs[job_id]
        self._running -= 1

    def _update_finished(self, job_id):
        """Check our status enum"""
        if self._jobs[job_id].get_status() in ["failed", "finished"]:
            self.finish_job_id(job_id)

    def run_job(self, job):
        # TODO: logger
        print("agent: got job", job)
        # parse job
        # todo: this will only let us launch runs from wandb (not eg github)
        run_spec = job["runSpec"]

        wandb_entity = run_spec.get("entity")
        wandb_project = run_spec.get("project")
        resource = run_spec.get("resource") or "local"
        name = run_spec.get("name")
        uri = run_spec["uri"]

        self._backend = load_backend(resource, self._api)
        self.verify()

        run_config = {}
        args_dict = {}
        entry_point = None

        if run_spec.get("overrides"):
            entry_point = run_spec["overrides"].get("entrypoint")
            args_dict = _collect_args(run_spec["overrides"].get("args", {}))
            run_config = run_spec["overrides"].get("run_config")
        user_id = None
        if run_spec.get("docker") and run_spec["docker"].get("user_id"):
            user_id = run_spec["docker"]["user_id"]

        git = run_spec.get("git")
        version = None
        if git:
            version = git.get("version")

        project = fetch_and_validate_project(
            uri,
            wandb_entity,
            wandb_project,
            name,
            self._api,
            version,
            entry_point,
            args_dict,
            user_id,
            run_config,
        )
        backend_config = dict(SYNCHRONOUS=True, DOCKER_ARGS={})
        if _is_wandb_local_uri(uri):
            backend_config[PROJECT_DOCKER_ARGS]["network"] = "host"

        if run_spec.get("docker_image"):
            backend_config["DOCKER_IMAGE"] = run_spec.get("docker_image")
        backend_config["runQueueItemId"] = job["runQueueItemId"]
        run = self._backend.run(project, backend_config)
        self._jobs[run.id] = run
        self._running += 1

    def loop(self):
        wandb.termlog(
            "launch agent polling project {}/{} on queues: {}".format(
                self._entity, self._project, ",".join(self._queues)
            )
        )
        try:
            while True:
                self._ticks += 1
                for queue in self._queues:
                    job = self.pop_from_queue(queue)
                    if job:
                        break
                if not job:
                    time.sleep(30)
                    # for job_id in self.job_ids:
                    # self._update_finished(job_id)
                    if self._ticks % 2 == 0:
                        self.print_status()
                    continue
                self.run_job(job)
        except KeyboardInterrupt:
            wandb.termlog("Shutting down, active jobs:")
            self.print_status()
