"""
Implementation of launch agent.
"""

import logging
import os
import time
from typing import Any, Dict, List, Optional, Union

import wandb
from wandb.apis.internal import Api
from wandb.sdk.launch.runner.local import LocalSubmittedRun
import wandb.util as util

from .._project_spec import create_project_from_spec, fetch_and_validate_project
from ..builder.loader import load_builder
from ..runner.abstract import AbstractRun
from ..runner.loader import load_backend
from ..utils import (
    PROJECT_DOCKER_ARGS,
    PROJECT_SYNCHRONOUS,
    resolve_build_and_registry_config,
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


class LaunchAgent:
    """Launch agent class which polls run given run queues and launches runs for wandb launch."""

    def __init__(self, api: Api, config: Dict[str, Any]):
        self._entity = config.get("entity")
        self._project = config.get("project")
        self._api = api
        self._base_url = self._api.settings().get("base_url")
        self._jobs: Dict[Union[int, str], AbstractRun] = {}
        self._ticks = 0
        self._running = 0
        self._cwd = os.getcwd()
        self._namespace = wandb.util.generate_id()
        self._access = _convert_access("project")
        if config.get("max_jobs") == -1:
            self._max_jobs = float("inf")
        else:
            self._max_jobs = config.get("max_jobs") or 1
        self.default_config: Optional[Dict[str, Any]] = config

        # serverside creation
        self.gorilla_supports_agents = (
            self._api.launch_agent_introspection() is not None
        )
        self._queues = config.get("queues", ["default"])
        create_response = self._api.create_launch_agent(
            self._entity,
            self._project,
            self._queues,
            self.gorilla_supports_agents,
        )
        self._id = create_response["launchAgentId"]
        self._name = ""  # hacky: want to display this to the user but we don't get it back from gql until polling starts. fix later

    @property
    def job_ids(self) -> List[Union[int, str]]:
        """Returns a list of keys running job ids for the agent."""
        return list(self._jobs.keys())

    def pop_from_queue(self, queue: str) -> Any:
        """Pops an item off the runqueue to run as a job."""
        try:
            ups = self._api.pop_from_run_queue(
                queue,
                entity=self._entity,
                project=self._project,
                agent_id=self._id,
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
            wandb.termerror(f"Failed to update agent status to {status}")

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
        try:
            if self._jobs[job_id].get_status().state in ["failed", "finished"]:
                self.finish_job_id(job_id)
        except Exception:
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

        backend_config["runQueueItemId"] = job["runQueueItemId"]
        _logger.info("Loading backend")
        override_build_config = launch_spec.get("build")
        override_registry_config = launch_spec.get("registry")

        build_config, registry_config = resolve_build_and_registry_config(
            self.default_config, override_build_config, override_registry_config
        )
        builder = load_builder(build_config)
        backend = load_backend(resource, self._api, backend_config)
        backend.verify()
        _logger.info("Backend loaded...")
        run = backend.run(project, builder, registry_config)
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

                agent_response = self._api.get_launch_agent(
                    self._id, self.gorilla_supports_agents
                )
                self._name = agent_response[
                    "name"
                ]  # hacky, but we don't return the name on create so this is first time
                if agent_response["stopPolling"]:
                    # shutdown process and all jobs if requested from ui
                    raise KeyboardInterrupt
                if self._running < self._max_jobs:
                    # only check for new jobs if we're not at max
                    for queue in self._queues:
                        job = self.pop_from_queue(queue)
                        if job:
                            try:
                                self.run_job(job)
                            except Exception as e:
                                wandb.termerror(f"Error running job: {e}")
                                self._api.ack_run_queue_item(job["runQueueItemId"])
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
