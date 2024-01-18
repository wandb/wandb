import asyncio
import logging
from typing import Any, Awaitable
from ..controller import LaunchControllerConfig
from ..job_set import JobSet
from ..builder import BuilderService
from ..registry import RegistryService

async def k8s_controller(
    config: LaunchControllerConfig,
    job_set: JobSet,
    logger: logging.Logger,
    builder: BuilderService,
    registry: RegistryService,
) -> Awaitable[Any]:
  name = config.job_set_spec["name"]
  iter = 0
  while True:
    logger.debug(f"[Controller {name}] Iter #{iter}")
    
    # Print out job set items
    logger.debug(f"[Controller {name}] Job set items:")
    async with job_set.lock:
      job_set_items = job_set.jobs
      for item in job_set_items:
        logger.debug(f"[Controller {name}]   {item}")
      
    await asyncio.sleep(5)
    iter += 1
