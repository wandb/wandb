from .agent import LaunchAgent2
from .job_set import JobSet, create_job_set

from .controllers import local_process

LaunchAgent = LaunchAgent2
JobSet = JobSet

__all__ = ["LaunchAgent", "JobSet", "create_job_set"]
