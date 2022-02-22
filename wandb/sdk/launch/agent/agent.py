"""
Implementation of launch agent.
"""

import logging
import os
import sys
import time
from typing import Any, Dict, Iterable, List, Union

import wandb
from wandb.apis.internal import Api
from wandb.sdk.launch.runner.local import LocalSubmittedRun
import wandb.util as util

from .._project_spec import create_project_from_spec, fetch_and_validate_project
from ..runner.abstract import AbstractRun
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

_logger = logging.getLogger(__name__)


def _convert_access(access: str) -> str:
    """Converts access string to a value accepted by wandb."""
    access = access.upper()
    assert (
        access == "PROJECT" or access == "USER"
    ), "Queue access must be either project or user"
    return access


class LaunchAgent(object):
    """Launch agent class which polls run given run queues and launches runs for wandb launch."""

    def __init__(
        self,
        entity: str,
        project: str,
        queues: Iterable[str] = None,
        max_jobs: int = None,
    ):
        self._entity = entity
        self._project = project
        self._api = Api()
        self._settings = wandb.Settings()
        self._base_url = self._api.settings().get("base_url")
        self._jobs: Dict[Union[int, str], AbstractRun] = {}
        self._ticks = 0
        self._running = 0
        self._cwd = os.getcwd()
        self._namespace = wandb.util.generate_id()
        self._access = _convert_access("project")
        self._max_jobs = max_jobs or 1

        # serverside creation
        self.gorilla_supports_agents = (
            self._api.launch_agent_introspection() is not None
        )
        create_response = self._api.create_launch_agent(
            entity, project, queues, self.gorilla_supports_agents
        )
        self._id = create_response["launchAgentId"]
        self._name = ""  # hacky: want to display this to the user but we don't get it back from gql until polling starts. fix later
        self._queues = queues if queues else ["default"]

    @property
    def job_ids(self) -> List[Union[int, str]]:
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
            "agent {} polling on project {}, queues {} for jobs".format(
                self._name, self._project, " ".join(self._queues)
            )
        )

    def update_status(self, status: str) -> None:
        update_ret = self._api.update_launch_agent_status(
            self._id, status, self.gorilla_supports_agents
        )
        if not update_ret["success"]:
            wandb.termerror("Failed to update agent status to {}".format(status))

    def finish_job_id(self, job_id: Union[str, int]) -> None:
        """Removes the job from our list for now."""
        # TODO:  keep logs or something for the finished jobs
        del self._jobs[job_id]
        self._running -= 1
        # update status back to polling if no jobs are running
        if self._running == 0:
            self.update_status(AGENT_POLLING)

    def _update_finished(self, job_id: Union[int, str]) -> None:
        """Check our status enum."""
        if self._jobs[job_id].get_status().state in ["failed", "finished"]:
            self.finish_job_id(job_id)

    def _validate_and_fix_spec_project_entity(
        self, launch_spec: Dict[str, Any]
    ) -> None:
        """Checks if launch spec target project/entity differs from agent. Forces these values to agent's if they are set."""
        if (
            launch_spec.get("project") is not None
            and launch_spec.get("project") != self._project
        ) or (
            launch_spec.get("entity") is not None
            and launch_spec.get("entity") != self._entity
        ):
            wandb.termwarn(
                f"Launch agents only support sending runs to their own project and entity. This run will be sent to {self._entity}/{self._project}"
            )
            launch_spec["entity"] = self._entity
            launch_spec["project"] = self._project

    def run_job(self, job: Dict[str, Any]) -> None:
        """Sets up project and runs the job."""
        # TODO: logger
        wandb.termlog(f"agent: got job f{job}")
        _logger.info(f"Agent job: {job}")
        # update agent status
        self.update_status(AGENT_RUNNING)

        # parse job
        _logger.info("Parsing launch spec")
        launch_spec = job["runSpec"]
        if launch_spec.get("overrides") and isinstance(
            launch_spec["overrides"].get("args"), list
        ):
            launch_spec["overrides"]["args"] = util._user_args_to_dict(
                launch_spec["overrides"].get("args", [])
            )
        self._validate_and_fix_spec_project_entity(launch_spec)

        project = create_project_from_spec(launch_spec, self._api)
        _logger.info("Fetching and validating project...")
        project = fetch_and_validate_project(project, self._api)
        _logger.info("Fetching resource...")
        resource = launch_spec.get("resource") or "local"
        backend_config: Dict[str, Any] = {
            PROJECT_DOCKER_ARGS: {},
            PROJECT_SYNCHRONOUS: False,  # agent always runs async
        }
        if _is_wandb_local_uri(self._base_url):
            _logger.info(
                "Noted a local URI. Setting local network arguments for docker"
            )
            if sys.platform == "win32":
                backend_config[PROJECT_DOCKER_ARGS]["net"] = "host"
            else:
                backend_config[PROJECT_DOCKER_ARGS]["network"] = "host"
            if sys.platform == "linux" or sys.platform == "linux2":
                backend_config[PROJECT_DOCKER_ARGS][
                    "add-host"
                ] = "host.docker.internal:host-gateway"

        backend_config["runQueueItemId"] = job["runQueueItemId"]
        _logger.info("Loading backend")
        backend = load_backend(resource, self._api, backend_config)
        backend.verify()
        _logger.info("Backend loaded...")
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
                if self._running < self._max_jobs:
                    # only check for new jobs if we're not at max
                    for queue in self._queues:
                        job = self.pop_from_queue(queue)
                        if job:
                            self.run_job(job)
                            break  # do a full housekeeping loop before popping more jobs

                agent_response = self._api.get_launch_agent(
                    self._id, self.gorilla_supports_agents
                )
                self._name = agent_response[
                    "name"
                ]  # hacky, but we don't return the name on create so this is first time
                if agent_response["stopPolling"]:
                    # shutdown process and all jobs if requested from ui
                    raise KeyboardInterrupt
                for job_id in self.job_ids:
                    self._update_finished(job_id)
                if self._ticks % 2 == 0:
                    if self._running == 0:
                        self.update_status(AGENT_POLLING)
                        self.print_status()
                    else:
                        self.update_status(AGENT_RUNNING)
                time.sleep(AGENT_POLLING_INTERVAL)

        except KeyboardInterrupt:
            # temp: for local, kill all jobs. we don't yet have good handling for different
            # types of runners in general
            for _, run in self._jobs.items():
                if isinstance(run, LocalSubmittedRun):
                    run.command_proc.kill()
            self.update_status(AGENT_KILLED)
            wandb.termlog("Shutting down, active jobs:")
            self.print_status()
