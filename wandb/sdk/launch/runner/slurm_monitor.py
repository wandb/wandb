import shlex
import subprocess
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import submitit

from wandb.sdk.launch.runner.abstract import State, Status

STATE_MAP: Dict[str, State] = {
    "UNKNOWN": "unknown",
    "PENDING": "starting",
    "REQUEUED": "starting",
    "READY": "running",
    "RUNNING": "running",
    "FAILED": "failed",
    "OUT_OF_MEMORY": "failed",
    "TIMEOUT": "failed",
    "COMPLETING": "stopping",
    "COMPLETED": "finished",
    "CANCELLED": "stopped",
    "STOPPED": "stopped",
    "SUSPENDED": "stopped",
    "PREEMPTED": "preempted",
}

# We only want one of these running to enforce rate limits
# TODO: maybe pull this from submitit
slurm_info = submitit.slurm.slurm.SlurmInfoWatcher(delay_s=600)


class SlurmJob(submitit.Job[submitit.core.core.R]):
    _cancel_command = "scancel"
    watcher = slurm_info

    def get_status(self) -> Status:
        # TODO: add more error context on failure
        state = self.watcher.get_state(self.job_id)
        clean_state = state.split(" ")[0]
        status = STATE_MAP.get(clean_state, "unknown")
        if status == "failed" or status == "starting":
            return Status(status, messages=[state])
        return Status(status)


class LaunchSlurmMonitor:
    """Monitors slurm resources managed by the launch agent."""

    _info = slurm_info

    def __init__(self):
        pass

    def _get_ts(self, d: datetime, sep="-", timespec="seconds"):
        return d.isoformat(sep, timespec)

    def list_jobs(self, since: Optional[datetime] = None):
        if since is None:
            since = datetime.now() - timedelta(days=1)
        ts = self._get_ts(since)
        cmd = [
            "sacct",
            "--format=JobID,JobName,State,Comment,ExitCode,Submit,Start,End,WorkDir,SubmitLine,NodeList,AllocTRES,Container,Priority,Extra",
            "-X",
            f"-S{ts}",
            "--parsable2",
        ]
        res = subprocess.check_output(cmd)
        return self._info.read_info(res)

    def get_status(self, job_id: str) -> Status:
        state = self._info.get_state(job_id).split(" ")[0]
        return Status(STATE_MAP.get(state, "unknown"))

    def get_script(self, job_id: str) -> str:
        cmd = ["sacct", "-j", shlex.quote(job_id), "-B"]
        res = subprocess.check_output(cmd)
        if not isinstance(res, str):
            res = res.decode()
        script = "\n".join(res.splitlines()[2:])
        return script

    def get_commands(self, job_id: str) -> List[str]:
        cmd = ["sacct", "-j", shlex.quote(job_id), "-o", "submitline", "-P"]
        res = subprocess.check_output(cmd)
        if not isinstance(res, str):
            res = res.decode()
        cmds = [cmd for cmd in res.splitlines()[1:] if len(cmd) > 0]
        return cmds
