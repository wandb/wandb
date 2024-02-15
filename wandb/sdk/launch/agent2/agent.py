import asyncio
import json
import logging
import sys
import traceback
from typing import Any, Dict, Optional, Set, TypedDict

import wandb
from wandb.apis.internal import Api
from wandb.sdk.launch import loader
from wandb.sdk.launch.agent.agent import HIDDEN_AGENT_RUN_TYPE
from wandb.sdk.launch.agent.job_status_tracker import JobAndRunStatusTracker
from wandb.sdk.launch.agent.run_queue_item_file_saver import RunQueueItemFileSaver
from wandb.sdk.launch.agent2.registry import RegistryService
from wandb.sdk.launch.builder.build import construct_agent_configs
from wandb.sdk.launch.utils import (
    LOG_PREFIX,
    PROJECT_SYNCHRONOUS,
    event_loop_thread_exec,
)

from .builder import BuilderService
from .controller import LaunchController, LegacyResources
from .job_set import JobSet, JobSetSpec, create_job_set


class AgentConfig(TypedDict):
    entity: str
    project: str
    max_jobs: int  # Deprecated; specified by each JobSet (see @max_concurrency metadata field)
    max_schedulers: int
    secure_mode: bool
    queues: list[str]
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
    def get_controller_for_job_set(cls, queue_type: str) -> LaunchController:
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
        self._builder = BuilderService()  # TODO
        self._registry = RegistryService()  # TODO
        self._job_sets: Dict[str, JobSet] = {}
        self._launch_controller_tasks: Set[asyncio.Task] = set()
        self._shutdown_controllers_event = asyncio.Event()
        self._shutdown_event = asyncio.Event()
        self._poll_interval = self._config.get("poll_interval", 5)
        self._last_state = None
        self._wandb_version: str = "wandb@" + wandb.__version__
        self._task = None
        self._logger = logging.getLogger("wandb.launch.agent2")
        self._logger.addHandler(logging.StreamHandler(sys.stdout))

        self._logger.info(f"[Agent] Got config: {json.dumps(self._config, indent=2)}")

        # ensure backend supports Launch Agent v2
        # self._logger.debug(f"[Agent ???] Checking backend for Launch Agent v2 support...")
        introspection_result = self._api.job_set_introspection()
        if introspection_result is None:
            raise NotImplementedError("Server does not support Launch Agent v2")

        # remove project field from agent config before sending to back end
        # because otherwise it shows up in the config in the UI and confuses users
        trimmed_config = dict(config.copy())
        if "project" in trimmed_config:
            del trimmed_config["project"]

        self._logger.debug("[Agent ???] Registering agent...")
        create_agent_result = self._api.create_launch_agent(
            self._config["entity"],
            self._config["project"],
            self._config["queues"],
            self._config,
            self._wandb_version,
            True,  # gorilla_agent_support
        )
        self._id = create_agent_result["launchAgentId"]

        get_agent_result = self._api.get_launch_agent(self._id, True)
        self._name = get_agent_result["name"]
        self._logger.info(f"[Agent {self._name}] Registered.")

        if self._api.entity_is_team(self._config["entity"]):
            self._logger.warn(
                f"{LOG_PREFIX}Agent is running on team entity ({self._config['entity']}). Members of this team will be able to run code on this device."
            )

        self._wandb_run = wandb.init(
            project=self._config["project"],
            entity=self._config["entity"],
            settings=wandb.Settings(silent=True, disable_git=True),
            id=self._name,
            job_type=HIDDEN_AGENT_RUN_TYPE,
        )

    async def loop(self) -> None:
        event_loop = asyncio.get_event_loop()

        # Start the main agent state poll loop
        self.start_poll_loop(event_loop)

        # Start job set and controller loops
        for q in self._config["queues"]:
            # Start a JobSet for each queue
            spec = JobSetSpec(
                name=q,
                entity_name=self._config["entity"],
                project_name=self._config["project"],
            )
            job_set = create_job_set(
                spec,
                self._api,
                self._id,
                self._logger,
            )
            self._job_sets[q] = job_set
            self._logger.debug(f"[Agent job_set.start_sync_loop {event_loop} ")
            job_set.start_sync_loop(event_loop)

            # Start a controller for each queue once job set is ready
            await job_set.ready()
            resource = job_set.metadata["@target_resource"]
            controller_impl = self.get_controller_for_job_set(resource)

            # Taken from original agent, need to factor this out
            _, build_config, registry_config = construct_agent_configs(self._config)
            environment = loader.environment_from_config(
                self._config.get("environment", {})
            )
            registry = loader.registry_from_config(registry_config, environment)
            builder = loader.builder_from_config(build_config, environment, registry)
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

            def file_saver_factory(job_id):
                return RunQueueItemFileSaver(self._wandb_run, job_id)

            def job_tracker_factory(job_id, q=q):
                return JobAndRunStatusTracker(job_id, q, file_saver_factory(job_id))

            legacy_resources = LegacyResources(
                self._api, builder, registry, runner, job_tracker_factory
            )

            controller_task = asyncio.create_task(
                controller_impl(
                    {
                        "agent_id": self._id,
                        "job_set_spec": spec,
                        "job_set_metadata": job_set.metadata,
                    },
                    job_set,
                    self._logger,
                    self._shutdown_controllers_event,
                    legacy_resources,
                )
            )
            self._launch_controller_tasks.add(controller_task)
            controller_task.add_done_callback(self._controller_done_callback)

        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            self._logger.info(f"{LOG_PREFIX}Main agent loop cancelled!")
        finally:
            await self.shutdown()

    def _controller_done_callback(self, task: asyncio.Task):
        try:
            task.result()
        except Exception:
            tb = traceback.format_exc()
            self._logger.error(
                f"{LOG_PREFIX}Controller task {task} failed with exception: {tb}"
            )
        finally:
            self._launch_controller_tasks.discard(task)

    async def shutdown(self):
        self._logger.info(f"{LOG_PREFIX}Shutting down...")
        # shut down all controllers
        self._shutdown_controllers_event.set()
        await asyncio.gather(*self._launch_controller_tasks)
        self._logger.info(f"{LOG_PREFIX}All controllers shut down.")

        # shut down all job_sets
        for job_set in self._job_sets.values():
            try:
                job_set.stop_sync_loop()
            except RuntimeError:
                # already stopped
                pass

        await asyncio.gather(
            *[job_set.wait_for_done for job_set in self._job_sets.values()]
        )
        self._logger.info(f"{LOG_PREFIX}All job sets shut down.")

        # shut down main poll loop
        self.stop_poll_loop()
        self._logger.info(f"{LOG_PREFIX}Main agent loop shut down.")

    # Agent polls for its own state
    async def _poll_loop(self):
        while not self._shutdown_event.is_set():
            self._logger.info(f"[Agent {self._id}] Polling...")
            await self._poll()
            await asyncio.sleep(self._poll_interval)
        self._logger.info(f"[Agent {self._id}] Shutting down poll loop...")

    async def _poll(self):
        self._logger.debug(f"[Agent {self._id}] Updating...")
        next_state = await self._fetch_agent_state()
        self._last_state = next_state
        self._logger.debug(
            f"[Agent {self._id}] Updated: {json.dumps(next_state, indent=2)}"
        )

    async def _fetch_agent_state(self):
        get_launch_agent = event_loop_thread_exec(self._api.get_launch_agent)
        return await get_launch_agent(self._id)

    def start_poll_loop(self, loop: asyncio.AbstractEventLoop):
        if self._task is None:
            self._loop = loop
            self._shutdown_event.clear()
            self._logger.info(f"[Agent {self._id}] Starting poll loop")
            self._task = self._loop.create_task(self._poll_loop())
        else:
            raise RuntimeError("Tried to start Agent but already started")

    def stop_poll_loop(self):
        if self._task is not None:
            self._logger.info(f"[Agent {self._id}] Stopping poll loop")
            self._task.cancel()
            self._task = None
        else:
            raise RuntimeError("Tried to stop Agent but not started")
        self._logger.info(f"[Agent {self._id}] Poll loop stopped")


def create_and_run_agent2(api: Api, config: AgentConfig) -> None:
    agent = LaunchAgent2(api, config)
    try:
        asyncio.run(agent.loop())
    except asyncio.CancelledError:
        print("(Main Loop Cancelled)", file=sys.stderr)
        raise
