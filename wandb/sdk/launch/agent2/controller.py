import asyncio
from dataclasses import dataclass
import logging
from typing import Any, Awaitable, Callable, Dict, Protocol, TypedDict

from wandb.apis.internal import Api
from wandb.sdk.launch.agent.job_status_tracker import JobAndRunStatusTracker
from wandb.sdk.launch.builder.abstract import AbstractBuilder
from wandb.sdk.launch.registry.abstract import AbstractRegistry
from wandb.sdk.launch.runner.abstract import AbstractRunner

from .job_set import JobSet, JobSetSpec


class LaunchControllerConfig(TypedDict):
    agent_id: str
    job_set_spec: JobSetSpec
    job_set_metadata: Dict[str, Any]

@dataclass 
class LegacyResources:
    """Legacy resources for launch controllers.
    
    These may be removed/replaced in the future, but kept for now to ease migration to LA2.
    """
    api: Api
    builder: AbstractBuilder
    registry: AbstractRegistry
    runner: AbstractRunner
    job_tracker_factory: Callable[[str], JobAndRunStatusTracker]
        

class LaunchController(Protocol):
    """A LaunchController is an async function that receives a LaunchControllerConfig and
    a JobSet, and is expected to work continuously to run jobs in the JobSet until the
    JobSet is empty.
    
    To run a job, the controller must first lease the job by calling job_set.lease_job(id).
    
    Once the job is running, the controller must ack the job by calling job_set.ack_job(id).
   
    Once a job has finished, regardless of success/failure, JobSet will automatically remove it from the set. (TODO)
    
    The controller is responsible for cleaning up jobs once they are complete.
    
    Lastly, the controller must shut down when the shutdown_event is set, or else it will
    be killed after 30 seconds. (TODO)
    
    Where appropriate, the controller should honor the configuration specified in
    config.job_set_metadata, e.g., limiting the number of concurrent runs to
    config.job_set_metadata["@max_concurrency"].
    
    """
    def __call__(
        self,
        config: LaunchControllerConfig,
        job_set: JobSet,
        logger: logging.Logger,
        shutdown_event: asyncio.Event,
        legacy: LegacyResources,
        ) -> Awaitable[Any]:
        ...