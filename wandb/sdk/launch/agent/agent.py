"""
Implementation of launch agent.
"""

import logging
import os
import pprint
import time
import traceback
from multiprocessing import Manager, Pool
from typing import Any, Dict, List, Union

import wandb
import wandb.util as util
from wandb.apis.internal import Api
from wandb.sdk.launch.runner.abstract import AbstractRun
from wandb.sdk.lib import runid

from .._project_spec import create_project_from_spec, fetch_and_validate_project
from ..builder.loader import load_builder
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


def init_pool_processes(jobs, lock):
    global _jobs
    global _lock
    _jobs = jobs
    _lock = lock


def thread_run_job(
    launch_spec: Dict[str, Any],
    job: Dict[str, Any],
    default_config: Dict[str, Any],
    api: Api,
):
    project = create_project_from_spec(launch_spec, api)
    _logger.info("Fetching and validating project...")
    project = fetch_and_validate_project(project, api)
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
        default_config, override_build_config, override_registry_config
    )
    builder = load_builder(build_config)

    default_runner = default_config.get("runner", {}).get("type")
    if default_runner == resource:
        backend_config["runner"] = default_config.get("runner")
    backend = load_backend(resource, api, backend_config)
    backend.verify()
    _logger.info("Backend loaded...")
    run = backend.run(project, builder, registry_config)

    if not run:
        return
    with _lock:
        _jobs[run.id] = 1
    while True:
        if _is_run_finished(run):
            with _lock:
                del _jobs[run.id]
            return
        time.sleep(AGENT_POLLING_INTERVAL)


def _is_run_finished(run: AbstractRun) -> None:
    """Check our status enum."""
    try:
        if run.get_status().state in ["failed", "finished"]:
            wandb.termlog(f"Job finished with ID: {run.id}")
            return True
        return False
    except Exception as e:
        if isinstance(e, LaunchError):
            wandb.termerror(f"Terminating job {run.id} because it failed to start:")
            wandb.termerror(str(e))
        _logger.info("---")
        _logger.info("Caught exception while getting status.")
        _logger.info(f"Job ID: {run.id}")
        _logger.info(traceback.format_exc())
        _logger.info("---")
        return True


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
        self._ticks = 0
        manager = Manager()
        self._jobs = manager.dict()
        _lock = manager.Lock()
        self._pool = Pool(initializer=init_pool_processes, initargs=(self._jobs, _lock))
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
        output_str = "agent "
        if self._name:
            output_str += f"{self._name} "
        if len(self._jobs.keys()) < self._max_jobs:
            output_str += "polling on "
            if self._project != LAUNCH_DEFAULT_PROJECT:
                output_str += f"project {self._project}, "
            output_str += f"queues {','.join(self._queues)}, "
        output_str += f"running {len(self._jobs.keys())} out of a maximum of {self._max_jobs} jobs"

        wandb.termlog(f"{LOG_PREFIX}{output_str}")
        if len(self._jobs.keys()) > 0:
            output_str += f": {','.join([str(key) for key in self._jobs.keys()])}"
        _logger.info(output_str)

    def update_status(self, status: str) -> None:
        update_ret = self._api.update_launch_agent_status(
            self._id, status, self.gorilla_supports_agents
        )
        if not update_ret["success"]:
            wandb.termerror(f"Failed to update agent status to {status}")

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

        self._pool.apply_async(
            thread_run_job,
            (
                launch_spec,
                job,
                self.default_config,
                self._api,
            ),
        )

    def loop(self) -> None:
        """Main loop function for agent."""
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
                if len(self._jobs.keys()) < self._max_jobs:
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
                if self._ticks % 2 == 0:
                    if len(self._jobs.keys()) == 0:
                        self.update_status(AGENT_POLLING)
                    else:
                        self.update_status(AGENT_RUNNING)
                    self.print_status()
                time.sleep(AGENT_POLLING_INTERVAL)

        except KeyboardInterrupt:
            self.update_status(AGENT_KILLED)
            wandb.termlog(f"{LOG_PREFIX}Shutting down, active jobs:")
            self.print_status()
