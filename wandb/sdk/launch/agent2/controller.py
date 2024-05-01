import asyncio
import logging
import sys
from dataclasses import dataclass
from typing import Any, Callable, Coroutine, Dict

if sys.version_info >= (3, 8):
    from typing import Protocol, TypedDict
else:
    from typing_extensions import Protocol, TypedDict

from wandb.apis.internal import Api
from wandb.sdk.launch.agent.job_status_tracker import JobAndRunStatusTracker
from wandb.sdk.launch.builder.abstract import AbstractBuilder
from wandb.sdk.launch.environment.abstract import AbstractEnvironment
from wandb.sdk.launch.registry.abstract import AbstractRegistry
from wandb.sdk.launch.runner.abstract import AbstractRunner

from .jobset import JobSet, JobSetSpec


class LaunchControllerConfig(TypedDict):
    agent_id: str
    jobset_spec: JobSetSpec
    jobset_metadata: Dict[str, Any]


@dataclass
class LegacyResources:
    """Legacy resources for launch controllers.

    These may be removed/replaced in the future, but kept for now to ease migration to LA2.
    """

    api: Api
    builder: AbstractBuilder
    registry: AbstractRegistry
    runner: AbstractRunner
    environment: AbstractEnvironment
    job_tracker_factory: Callable[[str, str], JobAndRunStatusTracker]


class LaunchController(Protocol):
    """An async controller for a Launch Queue.

    A LaunchController is an async function that receives a LaunchControllerConfig and
    a JobSet, and is expected to work continuously to run jobs in the JobSet until the
    JobSet is empty.

    To run a job, the controller must first lease the job by calling jobset.lease_job(id).

    Once the job is running, the controller must ack the job by calling jobset.ack_job(id).

    Once a job has finished, regardless of success/failure, JobSet will automatically remove it from the set. (TODO)

    The controller is responsible for cleaning up jobs once they are complete.

    Lastly, the controller must shut down when the shutdown_event is set, or else it will
    be killed after 30 seconds. (TODO)

    Where appropriate, the controller should honor the configuration specified in
    config.jobset_metadata, e.g., limiting the number of concurrent runs to
    config.jobset_metadata["@max_concurrency"].

    """

    def __call__(
        self,
        config: LaunchControllerConfig,
        jobset: JobSet,
        logger: logging.Logger,
        shutdown_event: asyncio.Event,
        legacy: LegacyResources,
        scheduler_queue: asyncio.Queue,
    ) -> Coroutine[Any, Any, Any]: ...
