"""Scheduler for classic wandb Sweeps."""
import logging
import queue
import socket
import time
from pprint import pformat as pf
from typing import Any, Dict, List

import wandb
from wandb.sdk.launch.sweeps import SchedulerError
from wandb.sdk.launch.sweeps.scheduler import (
    LOG_PREFIX,
    RunState,
    Scheduler,
    SchedulerState,
    SweepRun,
    _Worker,
)
from wandb.wandb_agent import _create_sweep_command_args

_logger = logging.getLogger(__name__)


class SweepScheduler(Scheduler):
    """A controller/agent that populates a Launch RunQueue from a sweeps RunQueue."""

    def __init__(
        self,
        *args: Any,
        num_workers: int = 8,
        heartbeat_queue_timeout: float = 1.0,
        heartbeat_queue_sleep: float = 1.0,
        **kwargs: Any,
    ):
        super().__init__(*args, **kwargs)
        self._num_workers: int = num_workers
        # Thread will pop items off the Sweeps RunQueue using AgentHeartbeat
        # and put them in this internal queue, which will be used to populate
        # the Launch RunQueue
        self._heartbeat_queue: "queue.Queue[SweepRun]" = queue.Queue()
        self._heartbeat_queue_timeout: float = heartbeat_queue_timeout
        self._heartbeat_queue_sleep: float = heartbeat_queue_sleep

    def _start(self) -> None:
        for worker_id in range(self._num_workers):
            _logger.debug(f"{LOG_PREFIX}Starting AgentHeartbeat worker {worker_id}\n")
            agent_config = self._api.register_agent(
                f"{socket.gethostname()}-{worker_id}",  # host
                sweep_id=self._sweep_id,
                project_name=self._project,
                entity=self._entity,
            )
            self._workers[worker_id] = _Worker(
                agent_config=agent_config,
                agent_id=agent_config["id"],
            )

    def _get_sweep_commands(self, worker_id: int) -> List[Dict[str, Any]]:
        # AgentHeartbeat wants a Dict of runs which are running or queued
        _run_states: Dict[str, bool] = {}
        for run_id, run in self._yield_runs():
            # Filter out runs that are from a different worker thread
            if run.worker_id == worker_id and run.state == RunState.ALIVE:
                _run_states[run_id] = True

        _logger.debug(f"{LOG_PREFIX}Sending states: \n{pf(_run_states)}\n")
        commands: List[Dict[str, Any]] = self._api.agent_heartbeat(
            self._workers[worker_id].agent_id,  # agent_id: str
            {},  # metrics: dict
            _run_states,  # run_states: dict
        )
        _logger.debug(f"{LOG_PREFIX}AgentHeartbeat commands: \n{pf(commands)}\n")

        return commands

    def _heartbeat(self, worker_id: int) -> bool:
        # Make sure Scheduler is alive
        if not self.is_alive():
            return False
        elif self.state == SchedulerState.FLUSH_RUNS:
            # already hit run_cap, just noop
            return False

        commands: List[Dict[str, Any]] = self._get_sweep_commands(worker_id)
        for command in commands:
            # The command "type" can be one of "run", "resume", "stop", "exit"
            _type = command.get("type")
            if _type in ["exit", "stop"]:
                run_cap = command.get("run_cap")
                if run_cap is not None:
                    # If Sweep hit run_cap, go into flushing state
                    wandb.termlog(f"{LOG_PREFIX}Sweep hit run_cap: {run_cap}")
                    self.state = SchedulerState.FLUSH_RUNS
                else:
                    # Tell (virtual) agent to stop running
                    self.state = SchedulerState.STOPPED
                return False

            if _type in ["run", "resume"]:
                _run_id = command.get("run_id")
                if not _run_id:
                    self.state = SchedulerState.FAILED
                    raise SchedulerError(f"No runId in agent heartbeat: {command}")
                if _run_id in self._runs:
                    wandb.termlog(f"{LOG_PREFIX}Skipping duplicate run: {_run_id}")
                    continue

                run = SweepRun(
                    id=_run_id,
                    args=command.get("args", {}),
                    logs=command.get("logs", []),
                    worker_id=worker_id,
                )
                self._runs[run.id] = run
                self._heartbeat_queue.put(run)
            else:
                self.state = SchedulerState.FAILED
                raise SchedulerError(f"AgentHeartbeat unknown command: {_type}")
        return True

    def _run(self) -> None:
        # Go through all workers and heartbeat
        for worker_id in self._workers:
            self._heartbeat(worker_id)

        for _worker_id in self._workers:
            try:
                run: SweepRun = self._heartbeat_queue.get(
                    timeout=self._heartbeat_queue_timeout
                )

                # If run is already stopped just ignore the request
                if run.state in [RunState.DEAD, RunState.UNKNOWN]:
                    wandb.termwarn(f"{LOG_PREFIX}Ignoring dead run {run.id}")
                    _logger.debug(f"dead run {run.id} state: {run.state}")
                    continue

                sweep_args = _create_sweep_command_args({"args": run.args})["args_dict"]
                launch_config = {"overrides": {"run_config": sweep_args}}
                self._add_to_launch_queue(run_id=run.id, config=launch_config)
            except queue.Empty:
                if self.state == SchedulerState.FLUSH_RUNS:
                    wandb.termlog(f"{LOG_PREFIX}Sweep stopped, waiting on runs...")
                else:
                    wandb.termlog(f"{LOG_PREFIX}No new runs to launch, waiting...")
                time.sleep(self._heartbeat_queue_sleep)
                return

    def _exit(self) -> None:
        pass
