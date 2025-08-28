import logging
from typing import Optional

from wandb.apis.internal import Api
from .job_status_tracker import JobAndRunStatusTracker

_logger = logging.getLogger(__name__)


class LaunchApiProvider:
    def __init__(self, agent_api: Api, agent_entity: str):
        self._agent_api = agent_api
        self._agent_entity = agent_entity
        self._job_api_cache: dict[str, Api] = {}  # Cache job APIs by run ID
    
    async def get_api(self, job_tracker: JobAndRunStatusTracker) -> Api:
        """Get the appropriate API instance for the given job context.
        
        Args:
            job_tracker: Job tracker for credential context (required)
            
        Returns:
            API instance with appropriate credentials (job credentials if available,
            otherwise agent credentials)
        """
        # Try job credentials first if we should use them
        if await self._should_use_job_credentials(job_tracker):
            job_api = await self._get_job_api(job_tracker)
            if job_api:
                return job_api
        
        # Fall back to agent credentials
        return self._agent_api
    
    async def _get_job_api(self, job_tracker: JobAndRunStatusTracker) -> Optional[Api]:
        """Get API instance for the job's credentials."""
        if not job_tracker.run:
            return None
            
        try:
            job_api_key = await job_tracker.run.get_job_api_key()
            if not job_api_key:
                return None

            run_id = job_tracker.run_id
            if run_id and run_id not in self._job_api_cache:
                self._job_api_cache[run_id] = Api(
                    api_key=job_api_key,
                    default_settings={"base_url": self._agent_api.api_url}
                )
            
            return self._job_api_cache.get(run_id) if run_id else None
        except Exception as e:
            _logger.warning(f"Failed to get job API for {job_tracker.run_queue_item_id}: {e}")
            return None
    
    async def _should_use_job_credentials(self, job_tracker: JobAndRunStatusTracker) -> bool:
        # Always prefer job credentials if available because a user may have
        # restricted projects in the same entity as the agent.
        if not job_tracker.run:
            return False
            
        try:
            job_api_key = await job_tracker.run.get_job_api_key()
            return job_api_key is not None
        except Exception:
            return False
    
    async def remove_job_api_from_cache(self, job_tracker: JobAndRunStatusTracker) -> None:
        if not job_tracker.run_id:
            return
            
        try:
            if job_tracker.run_id in self._job_api_cache:
                del self._job_api_cache[job_tracker.run_id]
        except Exception as e:
            _logger.debug(f"Failed to remove job API from cache: {e}")
