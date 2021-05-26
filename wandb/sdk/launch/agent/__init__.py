import getpass
import os
import tempfile
import time

import wandb
from wandb import Settings
from wandb.apis import internal_runqueue

from ..runner.abstract import AbstractRun, State
from ..runner.loader import load_backend

if wandb.TYPE_CHECKING:
    from typing import Dict


class LaunchAgent(object):
    STATE_MAP: Dict[str, State] = {}

    def __init__(
        self, entity: str, project: str, backend: str, max: int = 4, queues: str = None
    ):
        self._entity = entity
        self._project = project
        self._max = max
        self._api = internal_runqueue.Api()
        self._backend_name = backend
        self._backend = load_backend(backend, self._api)
        self._settings = Settings()
        self._jobs: Dict[str, AbstractRun] = {}
        self._ticks = 0
        self._running = 0
        self._cwd = os.getcwd()
        self._namespace = wandb.util.generate_id()
        self._access = "user"
        self.setup_run_queues(queues)

    def setup_run_queues(self, queues):
        project_run_queues = self._api.get_project_run_queues(self._entity, self._project)
        existing_run_queue_names = set([run_queue["name"] for run_queue in project_run_queues])
        if queues is None:
            print("queues is none")
            for queue in project_run_queues:
                if queue["name"] == "default":
                    self._queues = ["default"]
                    return
            self._api.create_run_queue(self._entity, self._project, "default", self._access)
            self._queues = ["default"]
            print(self._queues)
        else:
            for queue in queues:
                if queue not in existing_run_queue_names:
                    self._api.create_run_queue(self._entity, self._project, queue, self._access)
                self._queues.append(queue)

    @property
    def job_ids(self):
        return list(self._jobs.keys())

    def verify(self):
        return self._backend.verify()

    def check_queue(self, queue):
        try:
            ups = self._api.pop_from_run_queue(
                queue, entity=self._entity, project=self._project
            )
        except Exception as e:
            print("Exception...", e)
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

    def _spec_to_project(self, spec):
        # TODO: likely move this logic into the backend
        root = tempfile.mkdtemp()
        projo = os.path.join(root, "MLproject")
        conda = os.path.join(root, "conda.yaml")
        main = os.path.join(root, "main.py")
        with open(projo, "w") as f:
            f.write(
                """
name: auto
conda_env: conda.yaml
entry_points:
  main:
    command: "python main.py"
            """
            )
        with open(conda, "w") as f:
            f.write(
                """
dependencies:
  - numpy>=1.14.3
  - pandas>=1.0.0
  - pip
  - pip:
    - wandb
            """
            )
        with open(main, "w") as f:
            f.write(
                """
import wandb

wandb.init(project="test-launch")
wandb.log({"acc": 1})
            """
            )
        return root

    def run_job(self, job):
        # TODO: logger
        print("agent: got job", job)
        # spec = job.get("runSpec", {})
        # path = "."  # TODO: auto spec creation?  self._spec_to_project(spec)
        # version = None  # TODO: get commit from spec
        # params = None  # TODO: get parameters from spec
        # experiment_id = None  # TODO: likely used for grouping
        uri = "https://wandb.ai/{}/{}/runs/{}".format(job["runSpec"]["entity"], job["runSpec"]["project"], job["runSpec"]["run_id"])
        run = self._backend.run(
            uri,
            "main.py",
            backend_config=dict(BUILD_DOCKER=True),
            experiment_id=None,
            params=None,
            version="1.0"
        )
        self._jobs[run.id] = run
        self._running += 1
        self._api.ack_run_queue_item(job["runQueueItemId"], run.id)

    def loop(self):
        try:
            while True:
                self._ticks += 1
                for queue in self._queues:
                    job = self.check_queue(queue)
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
