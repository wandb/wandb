"""
Implementation of launch agent.
"""

import logging
import os
import pprint
import time
import traceback
from typing import Any, Dict, List, Union

import wandb
import wandb.util as util
from wandb.apis.internal import Api
from wandb.sdk.launch.runner.local_container import LocalSubmittedRun
from wandb.sdk.launch.sweeps import SCHEDULER_URI
from wandb.sdk.lib import runid

from .._project_spec import create_project_from_spec, fetch_and_validate_project
from ..builder.loader import load_builder
from ..runner.abstract import AbstractRun
from ..runner.loader import load_backend
from ..utils import (
    LAUNCH_DEFAULT_PROJECT,
    LOG_PREFIX,
    PROJECT_SYNCHRONOUS,
    LaunchError,
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


def _max_from_config(
    config: Dict[str, Any], key: str, default: int = 1
) -> Union[int, float]:
    """
    Utility for parsing integers from the agent config with
    a default, infinity handling, and integer parsing.
    Raises more informative error if parse error

    returns parsed value as int or infinity
    """
    try:
        val = config.get(key)
        if val is None:
            val = default
        max_from_config = int(val)
    except ValueError as e:
        raise Exception(
            f"Error when parsing LaunchAgent config key: ['{key}': "
            f"{config.get(key, default)}]. Error: {str(e)}"
        )
    if max_from_config == -1:
        return float("inf")
    return max_from_config


def _job_is_scheduler(run_spec: Dict[str, Any]) -> bool:
    """
    Utility for determining whether a job/runSpec is a sweep scheduler
    """
    if not run_spec:
        _logger.debug("Recieved runSpec in _job_is_scheduler that was empty")

    return run_spec.get("uri") == SCHEDULER_URI


class LaunchAgent:
    """Launch agent class which polls run given run queues and launches runs for wandb launch."""

    def __init__(self, api: Api, config: Dict[str, Any]):
        self._entity = config.get("entity")
        self._project = config.get("project")
        self._api = api
        self._base_url = self._api.settings().get("base_url")
        self._jobs: Dict[Union[int, str], AbstractRun] = {}
        self._schedulers: Dict[Union[int, str], AbstractRun] = {}
        self._ticks = 0
        self._cwd = os.getcwd()
        self._namespace = runid.generate_id()
        self._access = _convert_access("project")
        self._max_jobs = _max_from_config(config, "max_jobs")
        self._max_schedulers = _max_from_config(config, "max_schedulers")

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
        """Returns a list of keys running job ids for the agent."""
        return list(self._jobs.keys())

    @property
    def _running(self) -> int:
        """Returns number of scheduler and normal jobs"""
        return len(self._jobs) + len(self._schedulers)

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
        output_str = "agent "
        if self._name:
            output_str += f"{self._name} "
        if len(self._jobs) < self._max_jobs:
            output_str += "polling on "
            if self._project != LAUNCH_DEFAULT_PROJECT:
                output_str += f"project {self._project}, "
            output_str += f"queues {','.join(self._queues)}, "
        output_str += (
            f"running {len(self._jobs)} out of a maximum of {self._max_jobs} jobs"
        )

        wandb.termlog(f"{LOG_PREFIX}{output_str}")
        if self._running > 0:
            output_str += f": {','.join([str(key) for key in self._jobs.keys()])}"

        if len(self._schedulers) > 0:
            output_str += f": {','.join([str(key) for key in self._schedulers.keys()])}"

        _logger.info(output_str)

    def update_status(self, status: str) -> None:
        update_ret = self._api.update_launch_agent_status(
            self._id, status, self.gorilla_supports_agents
        )
        if not update_ret["success"]:
            wandb.termerror(f"Failed to update agent status to {status}")

    def _get_job_status(self, job_id: Union[str, int]) -> str:
        if job_id in self._jobs:
            return self._jobs[job_id].get_status().state
        elif job_id in self._schedulers:
            return self._jobs[job_id].get_status().state
        else:
            wandb.termerror(f"Got status of nonexistent job: {job_id}")
            return ""

    def _delete_job(self, job_id: Union[str, int]) -> None:
        """Deletion helper to handle both jobs and schedulers"""
        if job_id in self._jobs:
            del self._jobs[job_id]
        elif job_id in self._schedulers:
            del self._schedulers[job_id]
        else:
            wandb.termerror(f"Deleted nonexistent job: {job_id}")

    def finish_job_id(self, job_id: Union[str, int]) -> None:
        """Removes the job from our list for now."""
        # TODO:  keep logs or something for the finished jobs
        self._delete_job(job_id)

        # update status back to polling if no jobs are running
        if self._running == 0:
            self.update_status(AGENT_POLLING)

    def _update_finished(self, job_id: Union[int, str]) -> None:
        """Check our status enum."""
        try:
            status = self._get_job_status(job_id)
            if status in ["failed", "finished"]:
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
        """Sets up project and runs the job."""
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
        backend_config: Dict[str, Any] = {
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

        default_runner = self.default_config.get("runner", {}).get("type")
        if default_runner == resource:
            backend_config["runner"] = self.default_config.get("runner")
        backend = load_backend(resource, self._api, backend_config)
        backend.verify()
        _logger.info("Backend loaded...")
        run = backend.run(project, builder, registry_config)
        if run:
            if _job_is_scheduler(launch_spec):
                self._schedulers[run.id] = run
                wandb.termlog(
                    f"{LOG_PREFIX}Preparing to run sweep scheduler ({len(self._schedulers)}/{self._max_schedulers})"
                )
            else:
                self._jobs[run.id] = run

    def _poll_queues_and_run_jobs(self) -> None:
        """
        Go through all agent queues, attempt to pop jobs off the queue,
        check the scheduler count, and if all looks good run the job
        """
        for queue in self._queues:
            job = self.pop_from_queue(queue)
            if not job:
                continue

            if _job_is_scheduler(job.get("runSpec")):
                if len(self._schedulers) >= self._max_schedulers:
                    wandb.termwarn(
                        f"{LOG_PREFIX}Agent already running the maximum number "
                        f"of sweep schedulers: {self._max_schedulers}. To set "
                        "this value use `max_schedulers` key in the agent config"
                    )
                    continue

            try:
                self.run_job(job)
            except Exception:
                wandb.termerror(f"Error running job: {traceback.format_exc()}")
                self._api.ack_run_queue_item(job["runQueueItemId"])

    def loop(self) -> None:
        """Main loop function for agent."""
        self.print_status()
        try:
            while True:
                self._ticks += 1
                agent_response = self._api.get_launch_agent(
                    self._id, self.gorilla_supports_agents
                )
                self._name = agent_response["name"]  # hack: first time we get name
                if agent_response["stopPolling"]:
                    # shutdown process and all jobs if requested from ui
                    raise KeyboardInterrupt

                # only check for new jobs/schedulers if we're not at max JOBS
                if len(self._jobs) < self._max_jobs:
                    self._poll_queues_and_run_jobs()

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
            for _, run in {**self._jobs, **self._schedulers}.items():
                if isinstance(run, LocalSubmittedRun):
                    run.command_proc.kill()
            self.update_status(AGENT_KILLED)
            wandb.termlog(f"{LOG_PREFIX}Shutting down, active jobs:")
            self.print_status()
