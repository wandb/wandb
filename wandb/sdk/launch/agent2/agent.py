import asyncio
import json
import logging
import sys
import traceback
from typing import Any, Callable, Dict, List, Optional, Set

from wandb.sdk.launch.agent2.controllers.scheduler_controller import (
    SchedulerManager,
    scheduler_process_controller,
)

if sys.version_info >= (3, 8):
    from typing import TypedDict
else:
    from typing_extensions import TypedDict

import wandb
from wandb.apis.internal import Api
from wandb.sdk.launch import loader
from wandb.sdk.launch.agent.agent import HIDDEN_AGENT_RUN_TYPE, construct_agent_configs
from wandb.sdk.launch.agent.job_status_tracker import JobAndRunStatusTracker
from wandb.sdk.launch.agent.run_queue_item_file_saver import RunQueueItemFileSaver
from wandb.sdk.launch.builder.noop import NoOpBuilder
from wandb.sdk.launch.environment.local_environment import LocalEnvironment
from wandb.sdk.launch.registry.local_registry import LocalRegistry
from wandb.sdk.launch.utils import PROJECT_SYNCHRONOUS, event_loop_thread_exec

from .controller import LaunchController, LegacyResources
from .jobset import JobSet, JobSetSpec, JobWithQueue, create_jobset


class AgentConfig(TypedDict):
    entity: str
    project: str
    max_jobs: int  # Deprecated; specified by each JobSet (see @max_concurrency metadata field)
    max_schedulers: int
    secure_mode: bool
    queues: List[str]
    poll_interval: Optional[int]
    environment: Optional[Dict[str, Any]]


class LaunchAgent2:
    """Launch Agent v2 implementation."""

    _instance = None
    _initialized = False
    _controller_impls: Dict[str, LaunchController] = {}

    @classmethod
    def register_controller_impl(cls, queue_type: str, impl: LaunchController):
        if queue_type in cls._controller_impls:
            return  # Idempotent
        cls._controller_impls[queue_type] = impl

    @classmethod
    def get_controller_for_jobset(cls, queue_type: str) -> LaunchController:
        if queue_type not in cls._controller_impls:
            raise ValueError(f"No controller registered for queue type '{queue_type}'")
        return cls._controller_impls[queue_type]

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, api: Api, config: AgentConfig):
        if self._initialized:
            return
        self._initialized = True

        self._config = config
        self._api = api
        self._jobsets: Dict[str, JobSet] = {}
        self._launch_controller_tasks: Set[asyncio.Task] = set()
        self._shutdown_controllers_event = asyncio.Event()
        self._shutdown_event = asyncio.Event()
        self._poll_interval = self._config.get("poll_interval", 5)
        self._last_state = None
        self._wandb_version: str = "wandb@" + wandb.__version__
        self._task: Optional[asyncio.Task[Any]] = None
        self._sweep_scheduler_job_queue: asyncio.Queue[JobWithQueue] = asyncio.Queue()

        self._logger = logging.getLogger("wandb.launch.agent2")
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s")
        )
        self._logger.addHandler(handler)

        self._logger.info(f"Got config: {json.dumps(self._config, indent=2)}")

        # ensure backend supports Launch Agent v2
        introspection_result = self._api.jobset_introspection()
        if introspection_result is None:
            raise NotImplementedError("Server does not support Launch Agent v2")

        # remove project field from agent config before sending to back end
        # because otherwise it shows up in the config in the UI and confuses users
        trimmed_config = dict(config.copy())
        if "project" in trimmed_config:
            del trimmed_config["project"]

        self._logger.info("Registering with backend...")
        create_agent_result = self._api.create_launch_agent(
            self._config["entity"],
            "model-registry",
            self._config.get("queues", []),
            self._config,
            self._wandb_version,
            True,  # gorilla_agent_support
        )
        self._id = create_agent_result["launchAgentId"]

        get_agent_result = self._api.get_launch_agent(self._id, True)
        self._name = get_agent_result["name"]
        self._logger.info(f"Successfully registered with backend. name = {self._name}")

        if self._api.entity_is_team(self._config["entity"]):
            self._logger.warn(
                f"Agent is running on team entity ({self._config['entity']}). Members of this team will be able to run code on this machine."
            )

        self._wandb_run = wandb.init(
            project="model-registry",
            entity=self._config["entity"],
            settings=wandb.Settings(silent=True, disable_git=True),
            id=self._name,
            job_type=HIDDEN_AGENT_RUN_TYPE,
        )

    async def loop(self) -> None:
        event_loop = asyncio.get_event_loop()
        # Start the main agent state poll loop
        self.start_poll_loop(event_loop)

        def file_saver_factory(job_id):
            return RunQueueItemFileSaver(self._wandb_run, job_id)

        def job_tracker_factory(job_id, q):
            return JobAndRunStatusTracker(job_id, q, file_saver_factory(job_id))

        self._register_sweep_manager(job_tracker_factory)
        try:
            # Start job set and controller loops
            for q in self._config["queues"]:
                # Start a JobSet for each queue
                spec = JobSetSpec(
                    name=q,
                    entity_name=self._config["entity"],
                    project_name="model-registry",
                )
                jobset_logger = self._logger.getChild("jobset." + q)
                jobset = create_jobset(
                    spec,
                    self._api,
                    self._id,
                    jobset_logger,
                )
                self._jobsets[q] = jobset
                jobset.start_sync_loop(event_loop)

                # Start a controller for each queue once job set is ready
                await jobset.ready()
                resource = jobset.metadata["@target_resource"]
                controller_impl = self.get_controller_for_jobset(resource)

                # Taken from original agent, need to factor this out
                _, build_config, registry_config = construct_agent_configs(
                    dict(self._config)
                )
                environment = loader.environment_from_config(
                    self._config.get("environment", {})
                )
                registry = loader.registry_from_config(registry_config, environment)
                builder = loader.builder_from_config(
                    build_config, environment, registry
                )
                backend_config: Dict[str, Any] = {
                    PROJECT_SYNCHRONOUS: False,  # agent always runs async
                }
                runner = loader.runner_from_config(
                    resource,
                    self._api,  # todo factor out (?)
                    backend_config,
                    environment,
                    registry,
                )

                legacy_resources = LegacyResources(
                    self._api,
                    builder,
                    registry,
                    runner,
                    environment,
                    job_tracker_factory,
                )

                controller_logger = self._logger.getChild("controller." + q)

                controller_task: asyncio.Task = asyncio.create_task(
                    controller_impl(
                        {
                            "agent_id": self._id,
                            "jobset_spec": spec,
                            "jobset_metadata": jobset.metadata,
                        },
                        jobset,
                        controller_logger,
                        self._shutdown_controllers_event,
                        legacy_resources,
                        self._sweep_scheduler_job_queue,
                    )
                )
                self._launch_controller_tasks.add(controller_task)
                controller_task.add_done_callback(self._controller_done_callback)
        except Exception as e:
            self._logger.error(f"Agent init failed with exception: {e}")
            raise

        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            self._logger.info("Main agent loop cancelled!")
        finally:
            await self.shutdown()

    def _controller_done_callback(self, task: asyncio.Task):
        try:
            task.result()
        except Exception:
            tb = traceback.format_exc()
            self._logger.error(f"Controller task {task} failed with exception: {tb}")
        finally:
            self._launch_controller_tasks.discard(task)

    async def shutdown(self):
        self._logger.info("Shutting down agent...")
        # shut down all controllers
        self._shutdown_controllers_event.set()
        await asyncio.gather(*self._launch_controller_tasks)
        self._logger.info("All controllers shut down.")

        # shut down all jobsets
        for jobset in self._jobsets.values():
            try:
                jobset.stop_sync_loop()
            except RuntimeError:
                # already stopped
                pass

        await asyncio.gather(
            *[jobset.wait_for_done for jobset in self._jobsets.values()]
        )
        self._logger.info("All jobsets shut down.")

        # shut down main poll loop
        self.stop_poll_loop()
        self._logger.info("Main agent loop shut down.")

    # Agent polls for its own state
    async def _poll_loop(self):
        while not self._shutdown_event.is_set():
            self._logger.info("Polling...")
            await self._poll()
            await asyncio.sleep(self._poll_interval)
        self._logger.info("Shutting down agent poll loop...")

    async def _poll(self):
        next_state = await self._fetch_agent_state()
        self._last_state = next_state
        self._logger.debug(f"Agent state: {json.dumps(next_state)}")

    async def _fetch_agent_state(self):
        get_launch_agent = event_loop_thread_exec(self._api.get_launch_agent)

        return await get_launch_agent(self._id)

    def start_poll_loop(self, loop: asyncio.AbstractEventLoop):
        if self._task is None:
            self._loop = loop
            self._shutdown_event.clear()
            self._logger.info("Starting poll loop")
            self._task = self._loop.create_task(self._poll_loop())
        else:
            raise RuntimeError("Tried to start Agent but already started")

    def stop_poll_loop(self):
        if self._task is not None:
            self._logger.info("Stopping poll loop")
            self._task.cancel()
            self._task = None
        else:
            raise RuntimeError("Tried to stop Agent but not started")
        self._logger.info("Poll loop stopped")

    def _register_sweep_manager(
        self,
        job_tracker_factory: Callable[[str, str], JobAndRunStatusTracker],
    ):
        # create sweep scheduler local process controller
        environment = LocalEnvironment()
        registry = LocalRegistry()
        builder = NoOpBuilder({}, LocalEnvironment(), LocalRegistry())
        runner = loader.runner_from_config(
            "local-process",
            self._api,  # todo factor out (?)
            {
                PROJECT_SYNCHRONOUS: False,  # agent always runs async
            },
            environment,
            registry,
        )
        legacy_resources = LegacyResources(
            self._api,
            builder,
            registry,
            runner,
            environment,
            job_tracker_factory,
        )
        controller_logger = self._logger.getChild("controller.sweep-scheduler-manager")
        sweep_local_process_manager = SchedulerManager(
            self._api,
            self._config["max_schedulers"],
            legacy_resources,
            self._sweep_scheduler_job_queue,
            controller_logger,
        )
        manager_logger = self._logger.getChild("scheduler-manager")
        controller_task: asyncio.Task = asyncio.create_task(
            scheduler_process_controller(
                sweep_local_process_manager,
                self._config["max_schedulers"],
                manager_logger,
                self._shutdown_controllers_event,
                self._sweep_scheduler_job_queue,
            )
        )
        self._launch_controller_tasks.add(controller_task)
