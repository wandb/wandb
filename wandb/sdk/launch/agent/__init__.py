import getpass
import os
import tempfile
import time
from wandb.sdk import backend

import wandb
from wandb import Settings
from wandb.apis import internal_runqueue

from ..runner.abstract import AbstractRun, State
from ..runner.loader import load_backend
from ..utils import _convert_access, fetch_and_validate_project, _is_wandb_local_uri,  parse_wandb_uri, PROJECT_DOCKER_ARGS

if wandb.TYPE_CHECKING:
    from typing import Dict, Iterable


class LaunchAgent(object):
    STATE_MAP: Dict[str, State] = {}

    def __init__(
        self, entity: str, project: str, queues: Iterable[str] = None
    ):
        self._entity = entity
        self._project = project
        self._max = max
        self._api = internal_runqueue.Api()
        self._settings = Settings()
        self._base_url = self._api.settings().get("base_url")
        self._jobs: Dict[str, AbstractRun] = {}
        self._ticks = 0
        self._running = 0
        self._cwd = os.getcwd()
        self._namespace = wandb.util.generate_id()
        self._access = _convert_access("user")
        self._queues = []
        self._backend = None    # todo: probably rename to runner to avoid confusion w cli backend
        self.setup_run_queues(queues)

    def setup_run_queues(self, queues):
        project_run_queues = self._api.get_project_run_queues(self._entity, self._project)
        existing_run_queue_names = set([run_queue["name"] for run_queue in project_run_queues])
        if queues is None:
            for queue in project_run_queues:
                if queue["name"] == "default":
                    self._queues = ["default"]
                    return
            res = self._api.create_run_queue(self._entity, self._project, "default", self._access)
            success = res["success"]
            self._queues = ["default"]
        else:
            for queue in queues:
                success = True
                if queue not in existing_run_queue_names:
                    success = False
                    res = self._api.create_run_queue(self._entity, self._project, queue, self._access)
                    success = res["success"]
                if success:
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
        meta = {}
        for job_id in self.job_ids:
            status = self._jobs[job_id].status.state
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
        if self._jobs[job_id].get_status() in ["failed", "finished"]:
            self.finish_job_id(job_id)

    def run_job(self, job):
        # TODO: logger
        print("agent: got job", job)
        # parse job

        # todo: this will only let us launch runs from wandb (not eg github)
        run_spec = job["runSpec"]
        entity = run_spec["entity"]
        project = run_spec["project"]
        run_id = run_spec["run_id"]
        resource = run_spec["resource"]
        entry_point = run_spec["entry_point"]
        uri = "{}/{}/{}/runs/{}".format(self._base_url, entity, project, run_id)
        self._backend = load_backend(resource, self._api)
        self.verify()
        backend_config = dict(SYNCHRONOUS=True, DOCKER_ARGS=None, STORAGE_DIR=None)
        project = fetch_and_validate_project(uri, run_spec["name"], self._api, resource, run_spec.get("version", None), entry_point, run_spec.get("parameters", {}))
        if _is_wandb_local_uri(uri):
            backend_config[PROJECT_DOCKER_ARGS]["network"] = "host"
        run = self._backend.run(project, backend_config)
        self._jobs[run.id] = run
        self._running += 1
        self._api.ack_run_queue_item(job["runQueueItemId"], run.id)

    def loop(self):
        wandb.termlog("launch agent polling project {}/{} on queues: {}".format(self._entity, self._project, ",".join(self._queues)))
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
