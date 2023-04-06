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
from typing import Any, Dict, List, Optional, Union

import wandb
import wandb.util as util
from wandb.apis.internal import Api
from wandb.errors import CommError
from wandb.sdk.launch._project_spec import LaunchProject
from wandb.sdk.launch.runner.local_container import LocalSubmittedRun
from wandb.sdk.launch.sweeps import SCHEDULER_URI
from wandb.sdk.lib import runid

from .. import loader
from .._project_spec import create_project_from_spec, fetch_and_validate_project
from ..builder.build import construct_builder_args
from ..runner.abstract import AbstractRun
from ..utils import (
    LAUNCH_DEFAULT_PROJECT,
    LOG_PREFIX,
    PROJECT_SYNCHRONOUS,
    LaunchDockerError,
    LaunchError,
)

AGENT_POLLING_INTERVAL = 10
ACTIVE_SWEEP_POLLING_INTERVAL = 1  # more frequent when we know we have jobs

AGENT_POLLING = "POLLING"
AGENT_RUNNING = "RUNNING"
AGENT_KILLED = "KILLED"

MAX_THREADS = 64

_logger = logging.getLogger(__name__)


@dataclass
class JobAndRunStatus:
    run_queue_item_id: str
    run_id: Optional[str] = None
    project: Optional[str] = None
    run: Optional[AbstractRun] = None
    failed_to_start: bool = False
    completed: bool = False
    is_scheduler: bool = False

    @property
    def job_completed(self) -> bool:
        return self.completed or self.failed_to_start

    def update_run_info(self, launch_project: LaunchProject) -> None:
        self.run_id = launch_project.run_id
        self.project = launch_project.target_project


def _convert_access(access: str) -> str:
    """Convert access string to a value accepted by wandb."""
    access = access.upper()
    assert (
        access == "PROJECT" or access == "USER"
    ), "Queue access must be either project or user"
    return access


def _max_from_config(
    config: Dict[str, Any], key: str, default: int = 1
) -> Union[int, float]:
    """Get an integer from the config, or float.inf if -1.

    Utility for parsing integers from the agent config with a default, infinity
    handling, and integer parsing. Raises more informative error if parse error.
    """
    try:
        val = config.get(key)
        if val is None:
            val = default
        max_from_config = int(val)
    except ValueError as e:
        raise LaunchError(
            f"Error when parsing LaunchAgent config key: ['{key}': "
            f"{config.get(key)}]. Error: {str(e)}"
        )
    if max_from_config == -1:
        return float("inf")

    if max_from_config < 0:
        raise LaunchError(
            f"Error when parsing LaunchAgent config key: ['{key}': "
            f"{config.get(key)}]. Error: negative value."
        )
    return max_from_config


def _job_is_scheduler(run_spec: Dict[str, Any]) -> bool:
    """Determine whether a job/runSpec is a sweep scheduler."""
    if not run_spec:
        _logger.debug("Recieved runSpec in _job_is_scheduler that was empty")

    if run_spec.get("uri") != SCHEDULER_URI:
        return False

    if run_spec.get("resource") == "local-process":
        # If a scheduler is a local-process (100%), also
        #    confirm command is in format: [wandb scheduler <sweep>]
        cmd = run_spec.get("overrides", {}).get("entry_point", [])
        if len(cmd) < 3:
            return False

        if cmd[:2] != ["wandb", "scheduler"]:
            return False

    return True


class LaunchAgent:
    """Launch agent class which polls run given run queues and launches runs for wandb launch."""

    def __init__(self, api: Api, config: Dict[str, Any]):
        """Initialize a launch agent.

        Arguments:
            api: Api object to use for making requests to the backend.
            config: Config dictionary for the agent.
        """
        self._entity = config["entity"]
        self._project = config["project"]
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
        self._max_jobs = _max_from_config(config, "max_jobs")
        self._max_schedulers = _max_from_config(config, "max_schedulers")
        self._pool = ThreadPool(
            processes=int(min(MAX_THREADS, self._max_jobs + self._max_schedulers)),
            initargs=(self._jobs, self._jobs_lock),
        )
        self.default_config: Dict[str, Any] = config

        # serverside creation
        self.gorilla_supports_agents = (
            self._api.launch_agent_introspection() is not None
        )
        self._gorilla_supports_fail_run_queue_items = (
            self._api.fail_run_queue_item_introspection()
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
        if self._api.entity_is_team(self._entity):
            wandb.termwarn(
                f"{LOG_PREFIX}Agent is running on team entity ({self._entity}). Members of this team will be able to run code on this device."
            )

    def fail_run_queue_item(self, run_queue_item_id: str) -> None:
        if self._gorilla_supports_fail_run_queue_items:
            self._api.fail_run_queue_item(run_queue_item_id)

    @property
    def thread_ids(self) -> List[int]:
        """Returns a list of keys running thread ids for the agent."""
        with self._jobs_lock:
            return list(self._jobs.keys())

    @property
    def num_running_schedulers(self) -> int:
        """Return just the number of schedulers."""
        with self._jobs_lock:
            return len([x for x in self._jobs if self._jobs[x].is_scheduler])

    @property
    def num_running_jobs(self) -> int:
        """Return the number of jobs not including schedulers."""
        with self._jobs_lock:
            return len([x for x in self._jobs if not self._jobs[x].is_scheduler])

    def pop_from_queue(self, queue: str) -> Any:
        """Pops an item off the runqueue to run as a job.

        Arguments:
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
        output_str = "agent "
        if self._name:
            output_str += f"{self._name} "
        if self.num_running_jobs < self._max_jobs:
            output_str += "polling on "
            if self._project != LAUNCH_DEFAULT_PROJECT:
                output_str += f"project {self._project}, "
            output_str += f"queues {','.join(self._queues)}, "
        output_str += (
            f"running {self.num_running_jobs} out of a maximum of {self._max_jobs} jobs"
        )

        wandb.termlog(f"{LOG_PREFIX}{output_str}")
        if self.num_running_jobs > 0:
            output_str += f": {','.join(str(job_id) for job_id in self.thread_ids)}"

        _logger.info(output_str)

    def update_status(self, status: str) -> None:
        """Update the status of the agent.

        Arguments:
            status: Status to update the agent to.
        """
        update_ret = self._api.update_launch_agent_status(
            self._id, status, self.gorilla_supports_agents
        )
        if not update_ret["success"]:
            wandb.termerror(f"{LOG_PREFIX}Failed to update agent status to {status}")

    def finish_thread_id(self, thread_id: int) -> None:
        """Removes the job from our list for now."""
        job_and_run_status = self._jobs[thread_id]
        if not job_and_run_status.run_id or not job_and_run_status.project:
            self.fail_run_queue_item(job_and_run_status.run_queue_item_id)
        else:
            run_info = None
            # sweep runs exist but have no info before they are started
            # so run_info returned will be None
            # normal runs just throw a comm error
            try:
                run_info = self._api.get_run_info(
                    self._entity, job_and_run_status.project, job_and_run_status.run_id
                )

            except CommError:
                pass
            if run_info is None:
                self.fail_run_queue_item(job_and_run_status.run_queue_item_id)

        # TODO:  keep logs or something for the finished jobs
        with self._jobs_lock:
            del self._jobs[thread_id]

        # update status back to polling if no jobs are running
        if len(self.thread_ids) == 0:
            self.update_status(AGENT_POLLING)

    def _update_finished(self, thread_id: int) -> None:
        """Check our status enum."""
        with self._jobs_lock:
            job = self._jobs[thread_id]
        if job.job_completed:
            self.finish_thread_id(thread_id)

    def run_job(self, job: Dict[str, Any]) -> None:
        """Set up project and run the job.

        Arguments:
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
        """Loop infinitely to poll for jobs and run them.

        Raises:
            KeyboardInterrupt: if the agent is requested to stop.
        """
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
                if self.num_running_jobs < self._max_jobs:
                    # only check for new jobs if we're not at max
                    for queue in self._queues:
                        job = self.pop_from_queue(queue)
                        if job:
                            if _job_is_scheduler(job.get("runSpec")):
                                # If job is a scheduler, and we are already at the cap, ignore,
                                #    don't ack, and it will be pushed back onto the queue in 1 min
                                if self.num_running_schedulers >= self._max_schedulers:
                                    wandb.termwarn(
                                        f"{LOG_PREFIX}Agent already running the maximum number "
                                        f"of sweep schedulers: {self._max_schedulers}. To set "
                                        "this value use `max_schedulers` key in the agent config"
                                    )
                                    continue

                            try:
                                self.run_job(job)
                            except Exception as e:
                                wandb.termerror(
                                    f"{LOG_PREFIX}Error running job: {traceback.format_exc()}"
                                )
                                wandb._sentry.exception(e)
                                self.fail_run_queue_item(job["runQueueItemId"])

                for thread_id in self.thread_ids:
                    self._update_finished(thread_id)
                if self._ticks % 2 == 0:
                    if len(self.thread_ids) == 0:
                        self.update_status(AGENT_POLLING)
                    else:
                        self.update_status(AGENT_RUNNING)
                    self.print_status()

                if (
                    self.num_running_jobs == self._max_jobs
                    or self.num_running_schedulers == 0
                ):
                    # all threads busy or no schedulers running
                    time.sleep(AGENT_POLLING_INTERVAL)
                else:
                    time.sleep(ACTIVE_SWEEP_POLLING_INTERVAL)

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
        thread_id = threading.current_thread().ident
        assert thread_id is not None
        try:
            self._thread_run_job(launch_spec, job, default_config, api, thread_id)
        except LaunchDockerError as e:
            wandb.termerror(
                f"{LOG_PREFIX}agent {self._name} encountered an issue while starting Docker, see above output for details."
            )
            self.finish_thread_id(thread_id)
            wandb._sentry.exception(e)
        except Exception as e:
            wandb.termerror(f"{LOG_PREFIX}Error running job: {traceback.format_exc()}")
            self.finish_thread_id(thread_id)
            wandb._sentry.exception(e)

    def _thread_run_job(
        self,
        launch_spec: Dict[str, Any],
        job: Dict[str, Any],
        default_config: Dict[str, Any],
        api: Api,
        thread_id: int,
    ) -> None:
        job_tracker = JobAndRunStatus(job["runQueueItemId"])
        with self._jobs_lock:
            self._jobs[thread_id] = job_tracker
        project = create_project_from_spec(launch_spec, api)
        job_tracker.update_run_info(project)
        _logger.info("Fetching and validating project...")
        project = fetch_and_validate_project(project, api)
        _logger.info("Fetching resource...")
        resource = launch_spec.get("resource") or "local-container"
        backend_config: Dict[str, Any] = {
            PROJECT_SYNCHRONOUS: False,  # agent always runs async
        }
        _logger.info("Loading backend")
        override_build_config = launch_spec.get("builder")

        build_config, registry_config = construct_builder_args(
            default_config, override_build_config
        )

        environment = loader.environment_from_config(
            default_config.get("environment", {})
        )
        registry = loader.registry_from_config(registry_config, environment)
        builder = loader.builder_from_config(build_config, environment, registry)
        backend = loader.runner_from_config(resource, api, backend_config, environment)
        _logger.info("Backend loaded...")
        api.ack_run_queue_item(job["runQueueItemId"], project.run_id)
        run = backend.run(project, builder)

        if _job_is_scheduler(launch_spec):
            with self._jobs_lock:
                self._jobs[thread_id].is_scheduler = True
            wandb.termlog(
                f"{LOG_PREFIX}Preparing to run sweep scheduler "
                f"({self.num_running_schedulers}/{self._max_schedulers})"
            )

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
                if job_tracker.is_scheduler:
                    wandb.termlog(f"{LOG_PREFIX}Scheduler finished with ID: {run.id}")
                else:
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
        except Exception as e:
            wandb.termerror(f"{LOG_PREFIX}Error getting status for job {run.id}")
            wandb.termerror(traceback.format_exc())
            _logger.info("---")
            _logger.info("Caught exception while getting status.")
            _logger.info(f"Job ID: {run.id}")
            _logger.info(traceback.format_exc())
            _logger.info("---")
            wandb._sentry.exception(e)
        return known_error
