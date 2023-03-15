"""Abstract Scheduler class."""
import base64
import logging
import os
import yaml
import threading
import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Iterator, List, Optional, Tuple

import click

import wandb
import wandb.apis.public as public
from wandb.apis.internal import Api
from wandb.errors import CommError
from wandb.sdk.launch.launch_add import launch_add
from wandb.sdk.launch.sweeps import SchedulerError
from wandb.sdk.lib.runid import generate_id
from wandb.sdk.wandb_run import Run as SdkRun
from wandb.wandb_agent import Agent

_logger = logging.getLogger(__name__)
LOG_PREFIX = f"{click.style('sched:', fg='cyan')} "


@dataclass
class _Worker:
    agent_config: Dict[str, Any]
    agent_id: str


class SchedulerState(Enum):
    PENDING = 0
    STARTING = 1
    RUNNING = 2
    FLUSH_RUNS = 3
    COMPLETED = 4
    FAILED = 5
    STOPPED = 6
    CANCELLED = 7


class RunState(Enum):
    ALIVE = 0
    DEAD = 1
    UNKNOWN = 2


@dataclass
class SweepRun:
    id: str
    state: RunState = RunState.ALIVE
    queued_run: Optional[public.QueuedRun] = None
    args: Optional[Dict[str, Any]] = None
    logs: Optional[List[str]] = None
    # Threading can be used to run multiple workers in parallel
    worker_id: Optional[int] = None

    @property
    def full_name(self) -> Optional[str]:
        qr = self.queued_run
        if qr:
            return f"{qr.entity}/{qr.project}/{qr._run_id}"


class Scheduler(ABC):
    """A controller/agent that populates a Launch RunQueue from a hyperparameter sweep."""

    def __init__(
        self,
        api: Api,
        sweep_id: Optional[str] = None,
        entity: Optional[str] = None,
        project: Optional[str] = None,
        project_queue: Optional[str] = None,
        num_workers: int = 2,
        *args: Optional[Any],
        **kwargs: Optional[Any],
    ):
        self._api = api
        self._public_api = public.Api()
        self._entity = (
            entity
            or os.environ.get("WANDB_ENTITY")
            or api.settings("entity")
            or api.default_entity
        )
        self._project = (
            project or os.environ.get("WANDB_PROJECT") or api.settings("project")
        )
        self._sweep_id: str = sweep_id or "empty-sweep-id"
        self._state: SchedulerState = SchedulerState.PENDING

        # Make sure the provided sweep_id corresponds to a valid sweep
        try:
            resp = self._api.sweep(
                sweep_id, "{}", entity=self._entity, project=self._project
            )
            if resp.get("state") == SchedulerState.CANCELLED.name:
                self._state = SchedulerState.CANCELLED
            self._sweep_config = yaml.safe_load(resp["config"])
        except Exception as e:
            raise SchedulerError(f"{LOG_PREFIX}Exception when finding sweep: {e}")

        # Dictionary of the runs being managed by the scheduler
        self._runs: Dict[str, SweepRun] = {}
        # Threading lock to ensure thread-safe access to the runs dictionary
        self._threading_lock: threading.Lock = threading.Lock()
        self._project_queue = project_queue
        # Queue args
        self._queue_sleep = 5.0
        self._queue_timeout = 1.0
        # Optionally run multiple workers in (pseudo-)parallel. Workers do not
        # actually run training workloads, they simply send heartbeat messages
        # (emulating a real agent) and add new runs to the launch queue. The
        # launch agent is the one that actually runs the training workloads.
        self._workers: Dict[int, _Worker] = {}
        self._num_workers: int = num_workers

        # Scheduler may receive additional kwargs which will be piped into the launch command
        self._kwargs: Dict[str, Any] = kwargs

        # Scheduler controller run
        self._wandb_run: SdkRun = self._init_wandb_run()

    @abstractmethod
    def _start(self) -> None:
        pass

    @abstractmethod
    def _run(self) -> None:
        pass

    @abstractmethod
    def _exit(self) -> None:
        pass

    @abstractmethod
    def _save_state(self) -> None:
        pass

    @abstractmethod
    def _load_state(self) -> None:
        pass

    @property
    def state(self) -> SchedulerState:
        _logger.debug(f"{LOG_PREFIX}Scheduler state is {self._state.name}")
        return self._state

    @state.setter
    def state(self, value: SchedulerState) -> None:
        _logger.debug(f"{LOG_PREFIX}Scheduler was {self.state.name} is {value.name}")
        self._state = value

    def _init_wandb_run(self) -> SdkRun:
        """
        Controls resume or init logic for a scheduler wandb run
        """
        if self._kwargs.get("run_id"):  # resume
            # return wandb.init(
            #     project=self._project,
            #     id=self._kwargs["run_id"],
            #     resume="must"
            # )
            return wandb.init(resume=self._kwargs["run_id"])

        name = self._kwargs.get("sweep_type")

        return wandb.init(name=f"{name}-scheduler-{self._sweep_id}")

    def is_alive(self) -> bool:
        if self.state in [
            SchedulerState.COMPLETED,
            SchedulerState.FAILED,
            SchedulerState.STOPPED,
            SchedulerState.CANCELLED,
        ]:
            return False
        return True

    def start(self) -> None:
        """Start a scheduler, confirms prerequisites, begins execution loop."""
        wandb.termlog(f"{LOG_PREFIX}Scheduler starting.")
        if not self.is_alive():
            wandb.termerror(
                f"{LOG_PREFIX}Sweep already {self.state.name.lower()}! Exiting..."
            )
            self.exit()
            return

        self._state = SchedulerState.STARTING
        if not self._try_load_executable():
            self.exit()
            return

        self._load_state()
        self._start()
        self.run()

    def run(self) -> None:
        """Main run function for all external schedulers."""
        wandb.termlog(f"{LOG_PREFIX}Scheduler Running.")
        self.state = SchedulerState.RUNNING
        try:
            while True:
                if not self.is_alive():
                    break
                self._update_run_states()
                self._run()
                # if we hit the run_cap, now set to stopped after launching runs
                if self.state == SchedulerState.FLUSH_RUNS:
                    if len(self._runs.keys()) == 0:
                        wandb.termlog(f"{LOG_PREFIX}Done polling on runs, exiting.")
                        self.state = SchedulerState.STOPPED
        except KeyboardInterrupt:
            wandb.termwarn(
                f"{LOG_PREFIX}Scheduler received KeyboardInterrupt. Exiting."
            )
            self.state = SchedulerState.STOPPED
            self.exit()
            return
        except Exception as e:
            wandb.termerror(f"{LOG_PREFIX}Scheduler failed with exception {e}")
            self.state = SchedulerState.FAILED
            self.exit()
            raise e
        else:
            wandb.termlog(f"{LOG_PREFIX}Scheduler completed.")
            self.exit()

    def exit(self) -> None:
        self._exit()
        if self.state not in [
            SchedulerState.COMPLETED,
            SchedulerState.STOPPED,
        ]:
            self.state = SchedulerState.FAILED

        self._save_state()
        self._stop_runs()

    def _try_load_executable(self) -> bool:
        """Check existance of valid executable for a run.

        logs and returns False when job is unreachable
        """
        if self._kwargs.get("job"):
            try:
                _job_artifact = self._public_api.artifact(
                    self._kwargs["job"], type="job"
                )
                wandb.termlog(
                    f"{LOG_PREFIX}Successfully loaded job: {_job_artifact.name} in scheduler"
                )
            except Exception:
                wandb.termerror(f"{LOG_PREFIX}{traceback.format_exc()}")
                return False
            return True
        elif self._kwargs.get("image_uri"):
            # TODO(gst): check docker existance? Use registry in launch config?
            return True
        else:
            return False

    def _yield_runs(self) -> Iterator[Tuple[str, SweepRun]]:
        """Thread-safe way to iterate over the runs."""
        with self._threading_lock:
            yield from self._runs.items()

    def _stop_runs(self) -> None:
        to_delete = []
        for run_id, _ in self._yield_runs():
            to_delete += [run_id]

        for run_id in to_delete:
            wandb.termlog(f"{LOG_PREFIX}Stopping run {run_id}.")
            self._stop_run(run_id)

    def _stop_run(self, run_id: str) -> bool:
        """Stops a run and removes it from the scheduler"""
        if run_id in self._runs:
            run: SweepRun = self._runs[run_id]
            run.state = RunState.DEAD

            if not run.queued_run:
                _logger.debug(
                    f"tried to _stop_run but run not queued yet (run_id:{run.id})"
                )

            encoded_run_id = base64.standard_b64encode(
                f"Run:v1:{run_id}:{self._project}:{self._entity}".encode()
            ).decode("utf-8")

            # TODO(gst): improve performance here
            success = self._api.stop_run(
                run_id=encoded_run_id,
            )

            wandb.termlog(f"----- success: {success}")
            if success:
                wandb.termlog(f"{LOG_PREFIX}Stopped run {run_id}.")
            else:
                wandb.termlog(f"{LOG_PREFIX}Failed while stopping run {run_id}.")

            del self._runs[run_id]

            return success

    def _update_run_states(self) -> None:
        """
        Iterate through runs. Threadsafe.

        Get state from backend and deletes runs if not in running state.
        """
        _runs_to_remove: List[str] = []
        for run_id, run in self._yield_runs():
            try:
                _state = self._api.get_run_state(self._entity, self._project, run_id)
                _rqi_state = run.queued_run.state if run.queued_run else None
                if (
                    not _state
                    or _state
                    in [
                        "crashed",
                        "failed",
                        "killed",
                        "finished",
                    ]
                    or _rqi_state == "failed"
                ):
                    _logger.debug(
                        f"({run_id}) run-state:{_state}, rqi-state:{_rqi_state}"
                    )
                    run.state = RunState.DEAD
                    _runs_to_remove.append(run_id)
                elif _state in [
                    "running",
                    "pending",
                    "preempted",
                    "preempting",
                ]:
                    run.state = RunState.ALIVE
            except CommError as e:
                logging.debug(
                    f"{LOG_PREFIX}Issue when getting RunState for Run {run_id}: {e}"
                )
                run.state = RunState.UNKNOWN
                continue
        # Remove any runs that are dead
        with self._threading_lock:
            for run_id in _runs_to_remove:
                wandb.termlog(f"{LOG_PREFIX}Cleaning up dead run {run_id}.")
                del self._runs[run_id]

    def _add_to_launch_queue(
        self,
        run_id: Optional[str] = None,
        entry_point: Optional[List[str]] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> "public.QueuedRun":
        """Add a launch job to the Launch RunQueue.

        run_id: supplied by gorilla from agentHeartbeat
        entry_point: sweep entrypoint overrides image_uri/job entrypoint
        config: launch config
        """
        # job and image first from CLI args, then from sweep config
        _job = self._kwargs.get("job") or self._sweep_config.get("job")

        _sweep_config_uri = self._sweep_config.get("image_uri")
        _image_uri = self._kwargs.get("image_uri") or _sweep_config_uri
        if _job is None and _image_uri is None:
            raise SchedulerError(
                f"{LOG_PREFIX}No 'job' nor 'image_uri' (run: {run_id})"
            )
        elif _job is not None and _image_uri is not None:
            raise SchedulerError(f"{LOG_PREFIX}Sweep has both 'job' and 'image_uri'")

        if self._sweep_config.get("command"):
            entry_point = Agent._create_sweep_command(self._sweep_config["command"])
            wandb.termwarn(
                f"{LOG_PREFIX}Sweep command {entry_point} will override"
                f' {"job" if _job else "image_uri"} entrypoint'
            )

        run_id = run_id or generate_id()
        queued_run = launch_add(
            run_id=run_id,
            entry_point=entry_point,
            config=config,
            docker_image=_image_uri,  # TODO(gst): make agnostic (github? run uri?)
            job=_job,
            project=self._project,
            entity=self._entity,
            queue_name=self._kwargs.get("queue"),
            project_queue=self._project_queue,
            resource=self._kwargs.get("resource", None),
            resource_args=self._kwargs.get("resource_args", None),
            sweep_id=self._sweep_id,
        )
        self._runs[run_id].queued_run = queued_run
        wandb.termlog(
            f"{LOG_PREFIX}Added run to Launch queue: {self._kwargs.get('queue')} RunID:{run_id}."
        )
        return queued_run
