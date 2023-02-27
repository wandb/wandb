"""Implementation of launch agent."""
import logging
import os
import pprint
import threading
import time
import traceback
from dataclasses import dataclass
from multiprocessing import Event
from multiprocessing.pool import ThreadPool
from typing import Any, Dict, List, Optional

import wandb
import wandb.util as util
from wandb.apis.internal import Api
from wandb.sdk.launch.runner.local_container import LocalSubmittedRun
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

MAX_THREADS = 64

_logger = logging.getLogger(__name__)


@dataclass
class JobAndRunStatus:
    run: Optional[AbstractRun] = None
    failed_to_start: bool = False
    completed: bool = False

    @property
    def job_completed(self) -> bool:
        return self.completed or self.failed_to_start


def _convert_access(access: str) -> str:
    """Convert access string to a value accepted by wandb."""
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
        self._jobs: Dict[int, JobAndRunStatus] = {}
        self._jobs_lock = threading.Lock()
        self._jobs_event = Event()
        self._jobs_event.set()
        self._cwd = os.getcwd()
        self._namespace = runid.generate_id()
        self._access = _convert_access("project")
        max_jobs_from_config = int(config.get("max_jobs", 1))
        if max_jobs_from_config == -1:
            self._max_jobs = float("inf")
        else:
            self._max_jobs = max_jobs_from_config
        self._pool = ThreadPool(
            processes=int(min(MAX_THREADS, self._max_jobs)),
            # initializer=init_pool_processes,
            initargs=(self._jobs, self._jobs_lock),
        )
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
    def thread_ids(self) -> List[int]:
        """Returns a list of keys running thread ids for the agent."""
        return list(self._jobs.keys())

    @property
    def job_ids(self) -> List[str]:
        """Returns a list of keys running job ids for the agent."""
        job_ids: List[str] = []
        with self._jobs_lock:
            job_ids = [job.run.id for job in self._jobs.values() if job.run]
        return job_ids

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
        if len(self._jobs) > 0:
            output_str += f": {','.join(str(job_id) for job_id in self.job_ids)}"
        _logger.info(output_str)

    def update_status(self, status: str) -> None:
        update_ret = self._api.update_launch_agent_status(
            self._id, status, self.gorilla_supports_agents
        )
        if not update_ret["success"]:
            wandb.termerror(f"{LOG_PREFIX}Failed to update agent status to {status}")

    def finish_thread_id(self, thread_id: int) -> None:
        """Removes the job from our list for now."""
        # TODO:  keep logs or something for the finished jobs
        with self._jobs_lock:
            del self._jobs[thread_id]
        # update status back to polling if no jobs are running
        if len(self._jobs) == 0:
            self.update_status(AGENT_POLLING)

    def _update_finished(self, thread_id: int) -> None:
        """Check our status enum."""
        with self._jobs_lock:
            job = self._jobs[thread_id]
        if job.job_completed:
            self.finish_thread_id(thread_id)

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
            self.thread_run_job,
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
                if len(self._jobs) < self._max_jobs:
                    # only check for new jobs if we're not at max
                    for queue in self._queues:
                        job = self.pop_from_queue(queue)
                        if job:
                            try:
                                self.run_job(job)
                            except Exception:
                                wandb.termerror(
                                    f"{LOG_PREFIX}Error running job: {traceback.format_exc()}"
                                )
                                try:
                                    self._api.ack_run_queue_item(job["runQueueItemId"])
                                except Exception:
                                    _logger.error(
                                        f"{LOG_PREFIX}Error acking job when job errored: {traceback.format_exc()}"
                                    )

                for thread_id in self.thread_ids:
                    self._update_finished(thread_id)
                if self._ticks % 2 == 0:
                    if len(self._jobs) == 0:
                        self.update_status(AGENT_POLLING)
                    else:
                        self.update_status(AGENT_RUNNING)
                    self.print_status()
                time.sleep(AGENT_POLLING_INTERVAL)

        except KeyboardInterrupt:
            self._jobs_event.clear()
            self.update_status(AGENT_KILLED)
            wandb.termlog(f"{LOG_PREFIX}Shutting down, active jobs:")
            self.print_status()
            self._pool.close()
            self._pool.join()

    # Threaded functions
    def thread_run_job(
        self,
        launch_spec: Dict[str, Any],
        job: Dict[str, Any],
        default_config: Dict[str, Any],
        api: Api,
    ) -> None:

        try:
            self._thread_run_job(launch_spec, job, default_config, api)
        except Exception:
            wandb.termerror(f"{LOG_PREFIX}Error running job: {traceback.format_exc()}")
            api.ack_run_queue_item(job["runQueueItemId"])

    def _thread_run_job(
        self,
        launch_spec: Dict[str, Any],
        job: Dict[str, Any],
        default_config: Dict[str, Any],
        api: Api,
    ) -> None:
        thread_id = threading.current_thread().ident
        assert thread_id is not None
        job_tracker = JobAndRunStatus()
        with self._jobs_lock:
            self._jobs[thread_id] = job_tracker
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
            with self._jobs_lock:
                job_tracker.failed_to_start = True
            return
        with self._jobs_lock:
            job_tracker.run = run
        while self._jobs_event.is_set():
            if self._check_run_finished(job_tracker):
                return
            time.sleep(AGENT_POLLING_INTERVAL)
        # temp: for local, kill all jobs. we don't yet have good handling for different
        # types of runners in general
        if isinstance(run, LocalSubmittedRun):
            run.command_proc.kill()

    def _check_run_finished(self, job_tracker: JobAndRunStatus) -> bool:
        if job_tracker.completed:
            return True

        # the run can be done before the run has started
        # but can also be none if the run failed to start
        # so if there is no run, either the run hasn't started yet
        # or it has failed
        if job_tracker.run is None:
            if job_tracker.failed_to_start:
                return True
            return False

        known_error = False
        try:
            run = job_tracker.run
            status = run.get_status().state
            if status in ["stopped", "failed", "finished"]:
                wandb.termlog(f"{LOG_PREFIX}Job finished with ID: {run.id}")
                with self._jobs_lock:
                    job_tracker.completed = True
                return True
            return False
        except LaunchError as e:
            wandb.termerror(
                f"{LOG_PREFIX}Terminating job {run.id} because it failed to start: {str(e)}"
            )
            known_error = True
            with self._jobs_lock:
                job_tracker.failed_to_start = True
        # TODO: make get_status robust to errors for each runner, and handle them
        # TODO: add sentry to track this case and solve issues
        except Exception:
            wandb.termerror(f"{LOG_PREFIX}Error getting status for job {run.id}")
            wandb.termerror(traceback.format_exc())
            _logger.info("---")
            _logger.info("Caught exception while getting status.")
            _logger.info(f"Job ID: {run.id}")
            _logger.info(traceback.format_exc())
            _logger.info("---")
        return known_error
