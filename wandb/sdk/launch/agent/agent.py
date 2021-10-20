"""
Implementation of launch agent.
"""

import os
import sys
import time
from typing import Any, Dict, Iterable, List

import wandb
from wandb.apis.internal import Api
import wandb.util as util

from .._project_spec import create_project_from_spec, fetch_and_validate_project
from ..runner.abstract import AbstractRun, State
from ..runner.loader import load_backend
from ..utils import (
    _is_wandb_local_uri,
    PROJECT_DOCKER_ARGS,
    PROJECT_SYNCHRONOUS,
)

AGENT_POLLING_INTERVAL = 10

AGENT_POLLING = "POLLING"
AGENT_RUNNING = "RUNNING"
AGENT_KILLED = "KILLED"


def _convert_access(access: str) -> str:
    """Converts access string to a value accepted by wandb."""
    access = access.upper()
    assert (
        access == "PROJECT" or access == "USER"
    ), "Queue access must be either project or user"
    return access


class LaunchAgent(object):
    """Launch agent class which polls run given run queues and launches runs for wandb launch."""

    STATE_MAP: Dict[str, State] = {}

    def __init__(self, entity: str, project: str, queues: Iterable[str] = None):
        self._entity = entity
        self._project = project
        self._api = Api()
        self._settings = wandb.Settings()
        self._base_url = self._api.settings().get("base_url")
        self._jobs: Dict[int, AbstractRun] = {}
        self._ticks = 0
        self._running = 0
        self._cwd = os.getcwd()
        self._namespace = wandb.util.generate_id()
        self._access = _convert_access("project")

        # serverside creation
        self.gorilla_supports_agents = (
            self._api.launch_agent_introspection() is not None
        )
        create_response = self._api.create_launch_agent(
            entity, project, queues, self.gorilla_supports_agents
        )
        self._id = create_response["launchAgentId"]
        self._queues = queues if queues else ["default"]

    @property
    def job_ids(self) -> List[int]:
        """Returns a list of keys running job ids for the agent."""
        return list(self._jobs.keys())

    def pop_from_queue(self, queue: str) -> Any:
        """Pops an item off the runqueue to run as a job."""
        try:
            ups = self._api.pop_from_run_queue(
                queue, entity=self._entity, project=self._project, agent_id=self._id,
            )
        except Exception as e:
            print("Exception:", e)
            return None
        return ups

    def print_status(self) -> None:
        """Prints the current status of the agent."""
        wandb.termlog(
            "polling on project {}, queues {} for jobs".format(
                self._project, " ".join(self._queues)
            )
        )

    def finish_job_id(self, job_id: int) -> None:
        """Removes the job from our list for now."""
        # TODO:  keep logs or something for the finished jobs
        del self._jobs[job_id]
        self._running -= 1
        # update status back to polling if no jobs are running
        if self._running == 0:
            update_ret = self._api.update_launch_agent_status(
                self._id, AGENT_POLLING, self.gorilla_supports_agents
            )
            if not update_ret["success"]:
                wandb.termerror("Failed to update agent status to polling")

    def _update_finished(self, job_id: int) -> None:
        """Check our status enum."""
        if self._jobs[job_id].get_status().state in ["failed", "finished"]:
            self.finish_job_id(job_id)

    def run_job(self, job: Dict[str, Any]) -> None:
        """Sets up project and runs the job."""
        # TODO: logger
        wandb.termlog("agent: got job", job)
        # update agent status
        update_ret = self._api.update_launch_agent_status(
            self._id, AGENT_RUNNING, self.gorilla_supports_agents
        )
        if not update_ret["success"]:
            wandb.termerror("Failed to update agent status while running new job")

        # parse job
        launch_spec = job["runSpec"]
        if launch_spec.get("overrides") and isinstance(
            launch_spec["overrides"].get("args"), list
        ):
            launch_spec["overrides"]["args"] = util._user_args_to_dict(
                launch_spec["overrides"].get("args", [])
            )
        project = create_project_from_spec(launch_spec, self._api)
        project = fetch_and_validate_project(project, self._api)

        resource = launch_spec.get("resource") or "local"
        backend_config: Dict[str, Any] = {
            PROJECT_DOCKER_ARGS: {},
            PROJECT_SYNCHRONOUS: True,
        }
        if _is_wandb_local_uri(self._base_url):
            if sys.platform == "win32":
                backend_config[PROJECT_DOCKER_ARGS]["net"] = "host"
            else:
                backend_config[PROJECT_DOCKER_ARGS]["network"] = "host"
            if sys.platform == "linux" or sys.platform == "linux2":
                backend_config[PROJECT_DOCKER_ARGS][
                    "add-host"
                ] = "host.docker.internal:host-gateway"

        backend_config["runQueueItemId"] = job["runQueueItemId"]
        backend = load_backend(resource, self._api, backend_config)
        backend.verify()

        run = backend.run(project)
        if run:
            self._jobs[run.id] = run
            self._running += 1

    def loop(self) -> None:
        """Main loop function for agent."""
        wandb.termlog(
            "launch agent polling project {}/{} on queues: {}".format(
                self._entity, self._project, ",".join(self._queues)
            )
        )
        try:
            while True:
                self._ticks += 1
                job = None
                for queue in self._queues:
                    job = self.pop_from_queue(queue)
                    if job:
                        break
                if not job:
                    time.sleep(AGENT_POLLING_INTERVAL)
                    for job_id in self.job_ids:
                        self._update_finished(job_id)
                    if self._ticks % 2 == 0:
                        self.print_status()
                    continue
                self.run_job(job)
        except KeyboardInterrupt:
            shutdown_update = self._api.update_launch_agent_status(
                self._id, AGENT_KILLED, self.gorilla_supports_agents
            )
            if not shutdown_update["success"]:
                wandb.termerror("Failed to update agent status during shutdown")
            wandb.termlog("Shutting down, active jobs:")
            self.print_status()
