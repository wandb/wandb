import asyncio
import collections
import datetime
import json
import logging
import os
import shlex
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Set

import submitit

import wandb
from wandb.apis.internal import Api

from .._project_spec import LaunchProject
from ..errors import LaunchError
from ..utils import MAX_ENV_LENGTHS, PROJECT_SYNCHRONOUS
from .abstract import AbstractRun, AbstractRunner, Status
from .slurm_monitor import SlurmJob

_logger = logging.getLogger(__name__)


WANDB_RUN_ID_KEY = "wandb-run-id"


class SlurmSubmittedRun(AbstractRun):
    def __init__(self, job: SlurmJob) -> None:
        self._job = job

    @property
    def id(self) -> str:
        # numeric ID of the custom training job
        return self._job.job_id

    async def get_logs(self) -> Optional[str]:
        # TODO (slurm): the submitit library assumes naming we can't while remaining generic
        return self._job.stdout()

    async def get_status(self) -> Status:
        # TODO (slurm): figure out how to get failure messages from the slurm cluster and add them to messages
        status = self._job.get_status()
        return status

    async def wait(self) -> bool:
        # TODO (slurm): run this in a separate thread?
        await self._job.awaitable.wait()
        return self.get_status().state == "finished"

    async def cancel(self) -> None:
        self._job.cancel()


# TODO: maybe make this a subclass of LocalProcessRunner...
class SlurmRunner(AbstractRunner):
    """Runner class, uses a project to create a SlurmSubmittedRun."""

    def __init__(
        self,
        api: Api,
        backend_config: Dict[str, Any],
    ) -> None:
        """Initialize a SlurmRunner instance."""
        super().__init__(api, backend_config)
        settings = wandb.setup().settings
        self._wandb_dir = Path(settings.wandb_dir)

    def _update_build_log(self, env_name: str, env_hash: str) -> None:
        """The build-log keeps a record of when the last time a job is ran so we can cleanup old jobs."""
        history_path = self._wandb_dir / "agent-build-log.json"
        exists = history_path.exists()
        if exists:
            with open(history_path) as f:
                history = json.load(f)
        else:
            history = {"jobs": {}, "venvs": {}}
        with open(history_path, "w") as f:
            history["jobs"] = history.get("jobs", {})
            history["venvs"] = history.get("venvs", {})
            history["jobs"][env_name] = time.time()
            history["venvs"][env_hash] = time.time()
            json.dump(history, f)

    def _safe_symlink(
        self, base: str, target: str, name: str, delete: bool = False
    ) -> None:
        if not hasattr(os, "symlink"):
            return

        pid = os.getpid()
        tmp_name = os.path.join(base, "%s.%d" % (name, pid))

        if delete:
            try:
                os.remove(os.path.join(base, name))
            except OSError:
                pass
        target = os.path.relpath(target, base)
        try:
            os.symlink(target, tmp_name)
            os.rename(tmp_name, os.path.join(base, name))
        except OSError:
            pass

    async def cleanup(self, since: datetime.datetime) -> None:
        """Clean up old jobs."""
        # TODO: implement
        pass

    async def run(
        self, launch_project: LaunchProject, image_uri: str
    ) -> Optional[AbstractRun]:
        """Run a Slurm job."""
        full_resource_args = launch_project.fill_macros(image_uri)
        resource_args = full_resource_args.get("slurm")

        if not resource_args:
            raise LaunchError(
                "No Slurm resource args specified. Specify args via --resource-args"
            )

        self._update_build_log(launch_project.slurm_env_name, launch_project.env_hash)

        sbatch_args = resource_args.get("sbatch", {})
        conda_env = image_uri  # resource_args.get("conda-env", None)
        run_args = resource_args.get("run", {})

        synchronous: bool = self.backend_config[PROJECT_SYNCHRONOUS]

        entry_point = (
            launch_project.override_entrypoint or launch_project.get_job_entry_point()
        )

        entry_cmd = []
        if entry_point is not None:
            entry_cmd += entry_point.command

        # TODO: should probably just write a url here
        cmt = shlex.quote(f"{WANDB_RUN_ID_KEY}:{launch_project.run_id}")
        # TODO: make more robust
        if entry_cmd[0] == "sbatch":
            # TODO: handle bool and lists
            # TODO (slurm): we're removing unresolved vars which can happen when a job is launched
            # from the cli with --resource-args
            sbatch_args = [
                f"--{k}={shlex.quote(str(v))}"
                for k, v in sbatch_args.items()
                if "{{" not in str(v)
            ]
            # TODO (slurm): support --comment in command?
            entry_cmd = (
                [
                    "sbatch",
                    f"--comment={cmt}",
                    # "--export=ALL,WANDB_LAUNCH=true,WANDB_CONFIG={}",
                ]
                + sbatch_args
                + entry_cmd[1:]
            )
        # TODO (slurm): actually handle override args here, could we detect sbatch args?
        entry_cmd += launch_project.override_args

        if conda_env:
            env_flag = "-p" if "/" in conda_env else "-n"
            entry_cmd = ["conda", "run", env_flag, conda_env] + entry_cmd

        env_vars = launch_project.get_env_vars_dict(
            api=self._api,
            max_env_length=MAX_ENV_LENGTHS[self.__class__.__name__],
        )
        # Preserve our existing environment variables for slurm, conda, etc to work
        env_vars = {**os.environ.copy(), **env_vars}
        # Don't pass WANDB_SERVICE to the job as the job will run on a different host
        if "WANDB_SERVICE" in env_vars:
            env_vars.pop("WANDB_SERVICE")
        # To keep things tidier we tell our slurm jobs to write to the same wandb dir as the agent
        if "WANDB_DIR" not in env_vars:
            env_vars["WANDB_DIR"] = str(self._wandb_dir.parent)

        _logger.info("Launching slurm job...")
        cwd = Path(launch_project.project_dir, launch_project.job_build_context or "")
        wandb.termlog(f"Running sbatch from: {os.path.relpath(cwd, os.getcwd())}")
        self._safe_symlink(
            str(Path(launch_project._wandb_dir)),
            str(cwd),
            "latest-job",
        )
        submitted_run = await launch_slurm_job(
            launch_project,
            run_args,
            entry_cmd,
            env_vars,
            synchronous,
        )
        # TODO: update the build log when this fails or finishes
        return submitted_run


async def launch_slurm_job(
    launch_project: LaunchProject,
    run_args: Dict[str, Any],
    entry_cmd: List[str],
    environment: Dict[str, str],
    synchronous: bool = False,
) -> SlurmSubmittedRun:
    output = submitit.helpers.CommandFunction(
        entry_cmd,
        cwd=Path(launch_project.project_dir, launch_project.job_build_context or ""),
        env=environment,
        verbose=False,
    )()

    job_id = submitit.slurm.slurm.SlurmExecutor._get_job_id_from_submission_command(
        output
    )
    # TODO: this path should likely be a sub-path
    job = SlurmJob(launch_project.project_dir, job_id)
    if synchronous:
        # async_job = job.awaitable()
        await monitor_jobs([job])

    return SlurmSubmittedRun(job)


def _default_custom_logging(
    monitoring_start_time: float, n_jobs: int, state_jobs: Dict[str, Set[int]]
):
    run_time = time.time() - monitoring_start_time
    date_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    failed_job_indices = sorted(state_jobs["FAILED"])
    n_chars = len(str(n_jobs))

    wandb.termlog(
        f"[{date_time}] Launched {int(run_time / 60)} minutes ago,",
        f"{len(state_jobs['RUNNING']):{n_chars}}/{n_jobs} jobs running,",
        f"{len(failed_job_indices):{n_chars}}/{n_jobs} jobs failed,",
        f"{len(state_jobs['DONE']) - len(failed_job_indices):{n_chars}}/{n_jobs} jobs done",
    )

    if len(failed_job_indices) > 0:
        print(f"[{date_time}] Failed jobs, indices {failed_job_indices}", flush=True)


async def monitor_jobs(
    jobs: Sequence[submitit.core.core.Job[submitit.core.core.R]],
    poll_frequency: float = 5,
    test_mode: bool = False,
    custom_logging: Callable = _default_custom_logging,
) -> None:
    """Continuously monitors given jobs until they are all done or failed.

    Parameters
    ----------
    jobs: List[Jobs]
        A list of jobs to monitor
    poll_frequency: int
        The time (in seconds) between two refreshes of the monitoring.
        Can't be inferior to 30s.
    test_mode: bool
        If in test mode, we do not check the length of poll_frequency
    """
    if not test_mode:
        assert (
            poll_frequency >= 5
        ), "You can't refresh too often (>= 30s) to avoid overloading squeue"

    n_jobs = len(jobs)
    if n_jobs == 0:
        print("There are no jobs to monitor")
        return

    job_arrays = ", ".join(
        sorted(set(str(job.job_id).split("_", 1)[0] for job in jobs))
    )
    wandb.termlog(f"Monitoring {n_jobs} jobs from job arrays {job_arrays} \n")

    monitoring_start_time = time.time()
    state_jobs = collections.defaultdict(set)
    while True:
        if not test_mode:
            jobs[0].get_info(mode="force")  # Force update once to sync the state
        for i, job in enumerate(jobs):
            state_jobs[job.state.upper()].add(i)
            if job.done():
                state_jobs["DONE"].add(i)

        failed_job_indices = sorted(state_jobs["FAILED"])
        if len(state_jobs["DONE"]) == len(jobs):
            wandb.termlog(
                f"All jobs finished, jobs with indices {failed_job_indices} failed",
            )
            break

        custom_logging(monitoring_start_time, n_jobs, state_jobs)
        await asyncio.sleep(poll_frequency)
    wandb.termlog(
        f"Whole process is finished, took {int((time.time() - monitoring_start_time) / 60)} minutes"
    )
    for job in jobs:
        if job.state.upper() == "FAILED":
            wandb.termwarn(f"Job {job.job_id} failed:")
            if job.stderr():
                print(job.stderr())
            else:
                print(job.stdout())
