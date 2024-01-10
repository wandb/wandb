"""Implementation of launch agent."""
import asyncio
import logging
import os
import pprint
import threading
import time
import traceback
from dataclasses import dataclass
from multiprocessing import Event
from typing import Any, Dict, List, Optional, Union

import wandb
from wandb.apis.internal import Api
from wandb.errors import CommError
from wandb.sdk.launch._launch_add import launch_add
from wandb.sdk.launch.runner.local_container import LocalSubmittedRun
from wandb.sdk.launch.runner.local_process import LocalProcessRunner
from wandb.sdk.launch.sweeps.scheduler import Scheduler
from wandb.sdk.lib import runid

from .. import loader
from .._project_spec import (
    LaunchProject,
    create_project_from_spec,
    fetch_and_validate_project,
)
from ..builder.build import construct_agent_configs
from ..errors import LaunchDockerError, LaunchError
from ..utils import (
    LAUNCH_DEFAULT_PROJECT,
    LOG_PREFIX,
    PROJECT_SYNCHRONOUS,
    event_loop_thread_exec,
)
from .job_status_tracker import JobAndRunStatusTracker
from .run_queue_item_file_saver import RunQueueItemFileSaver

AGENT_POLLING_INTERVAL = 10
RECEIVED_JOB_POLLING_INTERVAL = 0.0  # more frequent when we know we have jobs

AGENT_POLLING = "POLLING"
AGENT_RUNNING = "RUNNING"
AGENT_KILLED = "KILLED"

HIDDEN_AGENT_RUN_TYPE = "sweep-controller"

MAX_RESUME_COUNT = 5

RUN_INFO_GRACE_PERIOD = 60

MAX_WAIT_RUN_STOPPED = 60

_env_timeout = os.environ.get("WANDB_LAUNCH_START_TIMEOUT")
if _env_timeout:
    try:
        RUN_START_TIMEOUT = float(_env_timeout)
    except ValueError:
        raise LaunchError(
            f"Invalid value for WANDB_LAUNCH_START_TIMEOUT: {_env_timeout}"
        )
else:
    RUN_START_TIMEOUT = 60 * 30  # default 30 minutes

_logger = logging.getLogger(__name__)


@dataclass
class JobSpecAndQueue:
    job: Dict[str, Any]
    queue: str


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


def _is_scheduler_job(run_spec: Dict[str, Any]) -> bool:
    """Determine whether a job/runSpec is a sweep scheduler."""
    if not run_spec:
        _logger.debug("Recieved runSpec in _is_scheduler_job that was empty")

    if run_spec.get("uri") != Scheduler.PLACEHOLDER_URI:
        return False

    if run_spec.get("resource") == "local-process":
        # Any job pushed to a run queue that has a scheduler uri is
        # allowed to use local-process
        if run_spec.get("job"):
            return True

        # If a scheduler is local-process and run through CLI, also
        #    confirm command is in format: [wandb scheduler <sweep>]
        cmd = run_spec.get("overrides", {}).get("entry_point", [])
        if len(cmd) < 3:
            return False

        if cmd[:2] != ["wandb", "scheduler"]:
            return False

    return True


class LaunchAgent:
    """Launch agent class which polls run given run queues and launches runs for wandb launch."""

    _instance = None

    def __new__(cls, *args: Any, **kwargs: Any) -> "LaunchAgent":
        """Create a new instance of the LaunchAgent.

        This method ensures that only one instance of the LaunchAgent is created.
        This is done so that information about the agent can be accessed from
        elsewhere in the library.
        """
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def name(cls) -> str:
        """Return the name of the agent."""
        if cls._instance is None:
            raise LaunchError("LaunchAgent has not been initialized")
        name = cls._instance._name
        if isinstance(name, str):
            return name
        raise LaunchError(f"Found invalid name for agent {name}")

    @classmethod
    def initialized(cls) -> bool:
        """Return whether the agent is initialized."""
        return cls._instance is not None

    def __init__(self, api: Api, config: Dict[str, Any]):
        """Initialize a launch agent.

        Arguments:
            api: Api object to use for making requests to the backend.
            config: Config dictionary for the agent.
        """
        self._entity = config["entity"]
        self._project = config.get("project", LAUNCH_DEFAULT_PROJECT)
        self._api = api
        self._base_url = self._api.settings().get("base_url")
        self._ticks = 0
        self._jobs: Dict[int, JobAndRunStatusTracker] = {}
        self._jobs_lock = threading.Lock()
        self._jobs_event = Event()
        self._jobs_event.set()
        self._cwd = os.getcwd()
        self._namespace = runid.generate_id()
        self._access = _convert_access("project")
        self._max_jobs = _max_from_config(config, "max_jobs")
        self._max_schedulers = _max_from_config(config, "max_schedulers")
        self._secure_mode = config.get("secure_mode", False)
        self.default_config: Dict[str, Any] = config

        # Get agent version from env var if present, otherwise wandb version
        self.version: str = "wandb@" + wandb.__version__
        env_agent_version = os.environ.get("WANDB_AGENT_VERSION")
        if env_agent_version and env_agent_version != "wandb-launch-agent":
            self.version = env_agent_version

        # serverside creation
        self.gorilla_supports_agents = (
            self._api.launch_agent_introspection() is not None
        )
        self._gorilla_supports_fail_run_queue_items = (
            self._api.fail_run_queue_item_introspection()
        )

        self._queues: List[str] = config.get("queues", ["default"])

        # remove project field from agent config before sending to back end
        # because otherwise it shows up in the config in the UI and confuses users
        sent_config = config.copy()
        if "project" in sent_config:
            del sent_config["project"]

        create_response = self._api.create_launch_agent(
            self._entity,
            self._project,
            self._queues,
            sent_config,
            self.version,
            self.gorilla_supports_agents,
        )
        self._id = create_response["launchAgentId"]
        if self._api.entity_is_team(self._entity):
            wandb.termwarn(
                f"{LOG_PREFIX}Agent is running on team entity ({self._entity}). Members of this team will be able to run code on this device."
            )

        agent_response = self._api.get_launch_agent(
            self._id, self.gorilla_supports_agents
        )
        self._name = agent_response["name"]
        self._init_agent_run()

    async def fail_run_queue_item(
        self,
        run_queue_item_id: str,
        message: str,
        phase: str,
        files: Optional[List[str]] = None,
    ) -> None:
        if self._gorilla_supports_fail_run_queue_items:
            fail_rqi = event_loop_thread_exec(self._api.fail_run_queue_item)
            await fail_rqi(run_queue_item_id, message, phase, files)

    def _init_agent_run(self) -> None:
        # TODO: has it been long enough that all backends support agents?
        if self.gorilla_supports_agents:
            settings = wandb.Settings(silent=True, disable_git=True)
            self._wandb_run = wandb.init(
                project=self._project,
                entity=self._entity,
                settings=settings,
                id=self._name,
                job_type=HIDDEN_AGENT_RUN_TYPE,
            )
        else:
            self._wandb_run = None

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

    async def pop_from_queue(self, queue: str) -> Any:
        """Pops an item off the runqueue to run as a job.

        Arguments:
            queue: Queue to pop from.

        Returns:
            Item popped off the queue.

        Raises:
            Exception: if there is an error popping from the queue.
        """
        try:
            pop = event_loop_thread_exec(self._api.pop_from_run_queue)
            ups = await pop(
                queue,
                entity=self._entity,
                project=self._project,
                agent_id=self._id,
            )
            return ups
        except Exception as e:
            print("Exception:", e)
            return None

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

    async def update_status(self, status: str) -> None:
        """Update the status of the agent.

        Arguments:
            status: Status to update the agent to.
        """
        _update_status = event_loop_thread_exec(self._api.update_launch_agent_status)
        update_ret = await _update_status(
            self._id, status, self.gorilla_supports_agents
        )
        if not update_ret["success"]:
            wandb.termerror(f"{LOG_PREFIX}Failed to update agent status to {status}")

    def _check_run_exists_and_inited(
        self, entity: str, project: str, run_id: str, rqi_id: str
    ) -> bool:
        """Checks the stateof the run to ensure it has been inited. Note this will not behave well with resuming."""
        # Checks the _wandb key in the run config for the run queue item id. If it exists, the
        # submitted run definitely called init. Falls back to checking state of run.
        # TODO: handle resuming runs

        # Sweep runs exist but are in pending state, normal launch runs won't exist
        # so will raise a CommError.
        try:
            run_state = self._api.get_run_state(entity, project, run_id)
            if run_state.lower() != "pending":
                return True
        except CommError:
            _logger.info(
                f"Run {entity}/{project}/{run_id} with rqi id: {rqi_id} did not have associated run"
            )
        return False

    async def finish_thread_id(
        self,
        thread_id: int,
        exception: Optional[Union[Exception, LaunchDockerError]] = None,
    ) -> None:
        """Removes the job from our list for now."""
        with self._jobs_lock:
            job_and_run_status = self._jobs[thread_id]
        if (
            job_and_run_status.entity is not None
            and job_and_run_status.entity != self._entity
        ):
            _logger.info(
                "Skipping check for completed run status because run is on a different entity than agent"
            )
        elif exception is not None:
            tb_str = traceback.format_exception(
                type(exception), value=exception, tb=exception.__traceback__
            )
            fnames = job_and_run_status.saver.save_contents(
                "".join(tb_str), "error.log", "error"
            )
            await self.fail_run_queue_item(
                job_and_run_status.run_queue_item_id,
                str(exception),
                job_and_run_status.err_stage,
                fnames,
            )
        elif job_and_run_status.project is None or job_and_run_status.run_id is None:
            _logger.error(
                f"called finish_thread_id on thread whose tracker has no project or run id. RunQueueItemID: {job_and_run_status.run_queue_item_id}"
            )
            wandb.termerror(
                "Missing project or run id on thread called finish thread id"
            )
            await self.fail_run_queue_item(
                job_and_run_status.run_queue_item_id,
                "submitted job was finished without assigned project or run id",
                "agent",
            )
        elif job_and_run_status.run is not None:
            called_init = False
            # We do some weird stuff here getting run info to check for a
            # created in run in W&B.
            #
            # We retry for 60 seconds with an exponential backoff in case
            # upsert run is taking a while.
            logs = None
            start_time = time.time()
            interval = 1
            while True:
                called_init = self._check_run_exists_and_inited(
                    self._entity,
                    job_and_run_status.project,
                    job_and_run_status.run_id,
                    job_and_run_status.run_queue_item_id,
                )
                if called_init or time.time() - start_time > RUN_INFO_GRACE_PERIOD:
                    break
                if not called_init:
                    # Fetch the logs now if we don't get run info on the
                    # first try, in case the logs are cleaned from the runner
                    # environment (e.g. k8s) during the run info grace period.
                    if interval == 1:
                        logs = await job_and_run_status.run.get_logs()
                    await asyncio.sleep(interval)
                    interval *= 2
            if not called_init:
                fnames = None
                if job_and_run_status.completed_status == "finished":
                    _msg = "The submitted job exited successfully but failed to call wandb.init"
                else:
                    _msg = "The submitted run was not successfully started"
                if logs:
                    fnames = job_and_run_status.saver.save_contents(
                        logs, "error.log", "error"
                    )
                await self.fail_run_queue_item(
                    job_and_run_status.run_queue_item_id, _msg, "run", fnames
                )
        else:
            _logger.info(f"Finish thread id {thread_id} had no exception and no run")
            wandb._sentry.exception(
                "launch agent called finish thread id on thread without run or exception"
            )

        # TODO:  keep logs or something for the finished jobs
        with self._jobs_lock:
            del self._jobs[thread_id]

        # update status back to polling if no jobs are running
        if len(self.thread_ids) == 0:
            await self.update_status(AGENT_POLLING)

    async def run_job(
        self, job: Dict[str, Any], queue: str, file_saver: RunQueueItemFileSaver
    ) -> None:
        """Set up project and run the job.

        Arguments:
            job: Job to run.
        """
        _msg = f"{LOG_PREFIX}Launch agent received job:\n{pprint.pformat(job)}\n"
        wandb.termlog(_msg)
        _logger.info(_msg)
        # update agent status
        await self.update_status(AGENT_RUNNING)

        # parse job
        _logger.info("Parsing launch spec")
        launch_spec = job["runSpec"]

        # Abort if this job attempts to override secure mode
        self._assert_secure(launch_spec)
        job_tracker = JobAndRunStatusTracker(job["runQueueItemId"], queue, file_saver)

        asyncio.create_task(
            self.task_run_job(
                launch_spec,
                job,
                self.default_config,
                self._api,
                job_tracker,
            )
        )

    def _assert_secure(self, launch_spec: Dict[str, Any]) -> None:
        """If secure mode is set, make sure no vulnerable keys are overridden."""
        if not self._secure_mode:
            return
        k8s_config = launch_spec.get("resource_args", {}).get("kubernetes", {})

        pod_secure_keys = ["hostPID", "hostIPC", "hostNetwork", "initContainers"]
        pod_spec = k8s_config.get("spec", {}).get("template", {}).get("spec", {})
        for key in pod_secure_keys:
            if key in pod_spec:
                raise ValueError(
                    f'This agent is configured to lock "{key}" in pod spec '
                    "but the job specification attempts to override it."
                )

        container_specs = pod_spec.get("containers", [])
        for container_spec in container_specs:
            if "command" in container_spec:
                raise ValueError(
                    'This agent is configured to lock "command" in container spec '
                    "but the job specification attempts to override it."
                )

        if launch_spec.get("overrides", {}).get("entry_point"):
            raise ValueError(
                'This agent is configured to lock the "entrypoint" override '
                "but the job specification attempts to override it."
            )

    async def loop(self) -> None:
        """Loop infinitely to poll for jobs and run them.

        Raises:
            KeyboardInterrupt: if the agent is requested to stop.
        """
        self.print_status()
        try:
            while True:
                job = None
                self._ticks += 1
                agent_response = self._api.get_launch_agent(
                    self._id, self.gorilla_supports_agents
                )
                if agent_response["stopPolling"]:
                    # shutdown process and all jobs if requested from ui
                    raise KeyboardInterrupt
                if self.num_running_jobs < self._max_jobs:
                    # only check for new jobs if we're not at max
                    job_and_queue = await self.get_job_and_queue()
                    # these will either both be None, or neither will be None
                    if job_and_queue is not None:
                        job = job_and_queue.job
                        queue = job_and_queue.queue
                        try:
                            file_saver = RunQueueItemFileSaver(
                                self._wandb_run, job["runQueueItemId"]
                            )
                            if _is_scheduler_job(job.get("runSpec", {})):
                                # If job is a scheduler, and we are already at the cap, ignore,
                                #    don't ack, and it will be pushed back onto the queue in 1 min
                                if self.num_running_schedulers >= self._max_schedulers:
                                    wandb.termwarn(
                                        f"{LOG_PREFIX}Agent already running the maximum number "
                                        f"of sweep schedulers: {self._max_schedulers}. To set "
                                        "this value use `max_schedulers` key in the agent config"
                                    )
                                    continue
                            await self.run_job(job, queue, file_saver)
                        except Exception as e:
                            wandb.termerror(
                                f"{LOG_PREFIX}Error running job: {traceback.format_exc()}"
                            )
                            wandb._sentry.exception(e)

                            # always the first phase, because we only enter phase 2 within the thread
                            files = file_saver.save_contents(
                                contents=traceback.format_exc(),
                                fname="error.log",
                                file_sub_type="error",
                            )
                            await self.fail_run_queue_item(
                                run_queue_item_id=job["runQueueItemId"],
                                message=str(e),
                                phase="agent",
                                files=files,
                            )

                if self._ticks % 2 == 0:
                    if len(self.thread_ids) == 0:
                        await self.update_status(AGENT_POLLING)
                    else:
                        await self.update_status(AGENT_RUNNING)
                    self.print_status()

                if self.num_running_jobs == self._max_jobs or job is None:
                    # all threads busy or did not receive job
                    await asyncio.sleep(AGENT_POLLING_INTERVAL)
                else:
                    await asyncio.sleep(RECEIVED_JOB_POLLING_INTERVAL)

        except KeyboardInterrupt:
            await self.update_status(AGENT_KILLED)
            wandb.termlog(f"{LOG_PREFIX}Shutting down, active jobs:")
            self.print_status()
        finally:
            self._jobs_event.clear()

    # Threaded functions
    async def task_run_job(
        self,
        launch_spec: Dict[str, Any],
        job: Dict[str, Any],
        default_config: Dict[str, Any],
        api: Api,
        job_tracker: JobAndRunStatusTracker,
    ) -> None:
        rqi_id = job["runQueueItemId"]
        assert rqi_id
        exception: Optional[Union[LaunchDockerError, Exception]] = None
        try:
            with self._jobs_lock:
                self._jobs[rqi_id] = job_tracker
            await self._task_run_job(
                launch_spec, job, default_config, api, rqi_id, job_tracker
            )
        except LaunchDockerError as e:
            wandb.termerror(
                f"{LOG_PREFIX}agent {self._name} encountered an issue while starting Docker, see above output for details."
            )
            exception = e
            wandb._sentry.exception(e)
        except LaunchError as e:
            wandb.termerror(f"{LOG_PREFIX}Error running job: {e}")
            exception = e
            wandb._sentry.exception(e)
        except Exception as e:
            wandb.termerror(f"{LOG_PREFIX}Error running job: {traceback.format_exc()}")
            exception = e
            wandb._sentry.exception(e)
        finally:
            await self.finish_thread_id(rqi_id, exception)

    async def _task_run_job(
        self,
        launch_spec: Dict[str, Any],
        job: Dict[str, Any],
        default_config: Dict[str, Any],
        api: Api,
        thread_id: int,
        job_tracker: JobAndRunStatusTracker,
    ) -> None:
        project = create_project_from_spec(launch_spec, api)
        self._set_queue_and_rqi_in_project(project, job, job_tracker.queue)
        ack = event_loop_thread_exec(api.ack_run_queue_item)
        await ack(job["runQueueItemId"], project.run_id)
        # don't launch sweep runs if the sweep isn't healthy
        await self.check_sweep_state(launch_spec, api)

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

        _, build_config, registry_config = construct_agent_configs(
            default_config, override_build_config
        )
        image_uri = project.docker_image
        entrypoint = project.get_single_entry_point()
        environment = loader.environment_from_config(
            default_config.get("environment", {})
        )
        registry = loader.registry_from_config(registry_config, environment)
        builder = loader.builder_from_config(build_config, environment, registry)
        backend = loader.runner_from_config(
            resource, api, backend_config, environment, registry
        )
        if not (project.docker_image or isinstance(backend, LocalProcessRunner)):
            assert entrypoint is not None
            image_uri = await builder.build_image(project, entrypoint, job_tracker)

        _logger.info("Backend loaded...")
        if isinstance(backend, LocalProcessRunner):
            run = await backend.run(project, image_uri)
        else:
            assert image_uri
            run = await backend.run(project, image_uri)
        if _is_scheduler_job(launch_spec):
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
        start_time = time.time()
        stopped_time: Optional[float] = None
        while self._jobs_event.is_set():
            # If run has failed to start before timeout, kill it
            state = (await run.get_status()).state
            if state == "starting" and RUN_START_TIMEOUT > 0:
                if time.time() - start_time > RUN_START_TIMEOUT:
                    await run.cancel()
                    raise LaunchError(
                        f"Run failed to start within {RUN_START_TIMEOUT} seconds. "
                        "If you want to increase this timeout, set WANDB_LAUNCH_START_TIMEOUT "
                        "to a larger value."
                    )
            if await self._check_run_finished(job_tracker, launch_spec):
                return
            if await job_tracker.check_wandb_run_stopped(self._api):
                if stopped_time is None:
                    stopped_time = time.time()
                else:
                    if time.time() - stopped_time > MAX_WAIT_RUN_STOPPED:
                        await run.cancel()
            await asyncio.sleep(AGENT_POLLING_INTERVAL)

        # temp: for local, kill all jobs. we don't yet have good handling for different
        # types of runners in general
        if isinstance(run, LocalSubmittedRun) and run._command_proc is not None:
            run._command_proc.kill()

    async def check_sweep_state(self, launch_spec: Dict[str, Any], api: Api) -> None:
        """Check the state of a sweep before launching a run for the sweep."""
        if launch_spec.get("sweep_id"):
            try:
                get_sweep_state = event_loop_thread_exec(api.get_sweep_state)
                state = await get_sweep_state(
                    sweep=launch_spec["sweep_id"],
                    entity=launch_spec["entity"],
                    project=launch_spec["project"],
                )
            except Exception as e:
                _logger.debug(f"Fetch sweep state error: {e}")
                state = None

            if state != "RUNNING" and state != "PAUSED":
                raise LaunchError(
                    f"Launch agent picked up sweep job, but sweep ({launch_spec['sweep_id']}) was in a terminal state ({state})"
                )

    async def _check_run_finished(
        self, job_tracker: JobAndRunStatusTracker, launch_spec: Dict[str, Any]
    ) -> bool:
        if job_tracker.completed_status:
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
            status = (await run.get_status()).state

            if status == "preempted" and job_tracker.entity == self._entity:
                config = launch_spec.copy()
                config["run_id"] = job_tracker.run_id
                config["_resume_count"] = config.get("_resume_count", 0) + 1
                with self._jobs_lock:
                    job_tracker.completed_status = status
                if config["_resume_count"] > MAX_RESUME_COUNT:
                    wandb.termlog(
                        f"{LOG_PREFIX}Run {job_tracker.run_id} has already resumed {MAX_RESUME_COUNT} times."
                    )
                    return True
                wandb.termlog(
                    f"{LOG_PREFIX}Run {job_tracker.run_id} was preempted, requeueing..."
                )

                if "sweep_id" in config:
                    # allow resumed runs from sweeps that have already completed by removing
                    # the sweep id before pushing to queue
                    del config["sweep_id"]

                launch_add(
                    config=config,
                    project_queue=self._project,
                    queue_name=job_tracker.queue,
                )
                return True
            # TODO change these statuses to an enum
            if status in ["stopped", "failed", "finished", "preempted"]:
                if job_tracker.is_scheduler:
                    wandb.termlog(f"{LOG_PREFIX}Scheduler finished with ID: {run.id}")
                    if status == "failed":
                        # on fail, update sweep state. scheduler run_id should == sweep_id
                        try:
                            self._api.set_sweep_state(
                                sweep=job_tracker.run_id,
                                entity=job_tracker.entity,
                                project=job_tracker.project,
                                state="CANCELED",
                            )
                        except Exception as e:
                            raise LaunchError(f"Failed to update sweep state: {e}")
                else:
                    wandb.termlog(f"{LOG_PREFIX}Job finished with ID: {run.id}")
                with self._jobs_lock:
                    job_tracker.completed_status = status
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

    async def get_job_and_queue(self) -> Optional[JobSpecAndQueue]:
        for queue in self._queues:
            job = await self.pop_from_queue(queue)
            if job is not None:
                self._queues.remove(queue)
                self._queues.append(queue)
                return JobSpecAndQueue(job, queue)
        return None

    def _set_queue_and_rqi_in_project(
        self, project: LaunchProject, job: Dict[str, Any], queue: str
    ) -> None:
        project.queue_name = queue

        # queue entity currently always matches the agent
        project.queue_entity = self._entity
        project.run_queue_item_id = job["runQueueItemId"]
