"""Implementation of launch agent."""

import logging
import os
import pprint
import time
import traceback
from typing import Any, Dict, List, Union

import wandb
import wandb.util as util
from wandb.apis.internal import Api
from wandb.errors import LaunchError
from wandb.sdk.launch.runner.local_container import LocalSubmittedRun
from wandb.sdk.lib import runid

from .util import (
    environment_from_config,
    registry_from_config,
    builder_from_config,
    create_runner,
)
from .._project_spec import (
    create_project_from_spec,
    fetch_and_validate_project,
    EntryPoint,
)
from ..builder.loader import load_builder
from ..runner.abstract import AbstractRun
from ..runner.loader import load_backend
from ..utils import (
    LAUNCH_DEFAULT_PROJECT,
    LOG_PREFIX,
    PROJECT_SYNCHRONOUS,
    resolve_build_and_registry_config,
)

AGENT_POLLING_INTERVAL = 10

AGENT_POLLING = "POLLING"
AGENT_RUNNING = "RUNNING"
AGENT_KILLED = "KILLED"

_logger = logging.getLogger(__name__)


def _convert_access(access: str) -> str:
    """Convert access string to a value accepted by wandb.

    Args:
        access: access string to convert.

    Returns:
        access string converted to a value accepted by wandb.

    Raises:
        AssertionError: if access is not either "project" or "user".
    """
    access = access.upper()
    assert (
        access == "PROJECT" or access == "USER"
    ), "Queue access must be either project or user"
    return access


class LaunchAgent:
    """Launch agent class which polls run given run queues and launches runs for wandb launch."""

    _entity: str
    _project: str
    _api: Api
    _base_url: str
    _jobs: Dict[Union[int, str], AbstractRun]
    _ticks: int
    _running: int
    _cwd: str
    _namespace: str
    _access: str
    _max_jobs: int
    default_config: Dict[str, Any]
    gorilla_supports_agents: bool
    _queues: List[str]
    _id: str
    _name: str

    def __init__(self, api: Api, config: Dict[str, Any]):
        """Initialize a launch agent.

        Args:
            api: Api object to use for making requests to the backend.
            config: Config dictionary for the agent.

        Raises:
            AssertionError: if config is missing the "entity" or "project" key.
        """
        self._entity = config.get("entity")
        self._project = config.get("project")
        self._api = api
        self._base_url = self._api.settings().get("base_url")
        self._jobs: Dict[Union[int, str], AbstractRun] = {}
        self._ticks = 0
        self._running = 0
        self._cwd = os.getcwd()
        self._namespace = runid.generate_id()
        self._access = _convert_access("project")
        max_jobs_from_config = int(config.get("max_jobs", 1))
        if max_jobs_from_config == -1:
            self._max_jobs = float("inf")
        else:
            self._max_jobs = max_jobs_from_config
        self.default_config: Dict[str, Any] = config

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
        """Returns a list of keys running job ids for the agent.

        Returns:
            List of running job ids.
        """
        return list(self._jobs.keys())

    def pop_from_queue(self, queue: str) -> Any:
        """Pops an item off the runqueue to run as a job.

        Args:
            queue: Queue to pop from.

        Returns:
            Item popped off the queue.

        Raises:
            Exception: if there is an error popping from the queue.
        """
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
        if self._running < self._max_jobs:
            output_str = f"agent {self._name} polling on "
            if self._project != LAUNCH_DEFAULT_PROJECT:
                output_str += "project {self._project}, "
            output_str += f"queues {','.join(self._queues)} while running {self._running} out of {self._max_jobs} jobs"
        else:
            output_str = (
                f"agent {self._name} running maximum number of jobs ({self._max_jobs})"
            )

        wandb.termlog(f"{LOG_PREFIX}{output_str}")
        if self._running > 0:
            output_str += f": {','.join([str(key) for key in self._jobs.keys()])}"
        _logger.info(output_str)

    def update_status(self, status: str) -> None:
        """Update the status of the agent.

        Args:
            status: Status to update the agent to.
        """
        update_ret = self._api.update_launch_agent_status(
            self._id, status, self.gorilla_supports_agents
        )
        if not update_ret["success"]:
            wandb.termerror(f"Failed to update agent status to {status}")

    def finish_job_id(self, job_id: Union[str, int]) -> None:
        """Remove the job from our list for now.

        Args:
            job_id: Id of the job to remove.
        """
        # TODO:  keep logs or something for the finished jobs
        del self._jobs[job_id]
        self._running -= 1
        # update status back to polling if no jobs are running
        if self._running == 0:
            self.update_status(AGENT_POLLING)

    def _update_finished(self, job_id: Union[int, str]) -> None:
        """Check our status enum.

        Args:
            job_id: Id of the job to update.
        """
        try:
            if self._jobs[job_id].get_status().state in ["failed", "finished"]:
                self.finish_job_id(job_id)
        except Exception as e:
            if isinstance(e, LaunchError):
                wandb.termerror(f"Terminating job {job_id} because it failed to start:")
                wandb.termerror(str(e))
            _logger.info("---")
            _logger.info("Caught exception while getting status.")
            _logger.info(f"Job ID: {job_id}")
            _logger.info(traceback.format_exc())
            _logger.info("---")
            self.finish_job_id(job_id)

    def run_job(self, job: Dict[str, Any]) -> None:
        """Set up project and run the job.

        Args:
            job: Job to run.
        """
        _msg = f"{LOG_PREFIX}Launch agent received job:\n{pprint.pformat(job)}\n"
        wandb.termlog(_msg)
        _logger.info(_msg)
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

        project = create_project_from_spec(launch_spec, self._api)
        _logger.info("Fetching and validating project...")
        project = fetch_and_validate_project(project, self._api)
        _logger.info("Fetching resource...")
        resource = launch_spec.get("resource") or "local-container"

        env_config = self.default_config.get("environment", {})
        print("hello", self.default_config)
        # print(env_config)
        environment = environment_from_config(env_config)

        registry_config = self.default_config.get("registry", {})
        registry = registry_from_config(registry_config, environment)

        builder_config = self.default_config.get("builder", {})
        builder = builder_from_config(builder_config, registry)
        # builder.build_image(project, EntryPoint("name", "main.py"))

        # print(builder)

        backend_config: Dict[str, Any] = {
            PROJECT_SYNCHRONOUS: False,  # agent always runs async
        }

        backend_config["runQueueItemId"] = job["runQueueItemId"]
        _logger.info("Loading backend")

        # # override_build_config = launch_spec.get("build")
        # # override_registry_config = launch_spec.get("registry")

        # # build_config, registry_config = resolve_build_and_registry_config(
        # #     self.default_config, override_build_config, override_registry_config
        # # )
        # # builder = load_builder(build_config)

        default_runner = self.default_config.get("runner", {}).get("type")
        if default_runner == resource:
            backend_config["runner"] = self.default_config.get("runner")

        backend = create_runner(resource, self._api, backend_config, environment)
        # backend = load_backend(resource, self._api, backend_config)
        backend.verify()
        _logger.info("Backend loaded...")
        run = backend.run(project, builder)
        if run:
            self._jobs[run.id] = run
            self._running += 1

    def loop(self) -> None:
        """Loop infinitely to poll for jobs and run them.

        Raises:
            KeyboardInterrupt: if the agent is requested to stop.
        """
        self.print_status()
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
                            except Exception:
                                wandb.termerror(
                                    f"Error running job: {traceback.format_exc()}"
                                )
                                self._api.ack_run_queue_item(job["runQueueItemId"])
                for job_id in self.job_ids:
                    self._update_finished(job_id)
                if self._ticks % 2 == 0:
                    if self._running == 0:
                        self.update_status(AGENT_POLLING)
                    else:
                        self.update_status(AGENT_RUNNING)
                    self.print_status()
                time.sleep(AGENT_POLLING_INTERVAL)

        except KeyboardInterrupt:
            # temp: for local, kill all jobs. we don't yet have good handling for different
            # types of runners in general
            for _, run in self._jobs.items():
                if isinstance(run, LocalSubmittedRun):
                    run.command_proc.kill()
            self.update_status(AGENT_KILLED)
            wandb.termlog(f"{LOG_PREFIX}Shutting down, active jobs:")
            self.print_status()
