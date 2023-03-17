"""Scheduler for classic wandb Sweeps."""
import logging
from pprint import pformat as pf
from typing import Any, Dict, List, Optional

import wandb
from wandb.sdk.launch.sweeps import SchedulerError
from wandb.sdk.launch.sweeps.scheduler import (
    LOG_PREFIX,
    RunState,
    Scheduler,
    SchedulerState,
    SweepRun,
)

_logger = logging.getLogger(__name__)


class SweepScheduler(Scheduler):
    """A controller/agent that populates a Launch RunQueue from a sweeps RunQueue."""

    def __init__(
        self,
        *args: Any,
        **kwargs: Any,
    ):
        super().__init__(*args, **kwargs)

    def _get_next_sweep_run(self, worker_id: int) -> Optional[SweepRun]:
        """Called by the main scheduler execution loop.

        Expected to return a properly formatted SweepRun if the scheduler
        is alive, or None and set the appropriate scheduler state
        """
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
                return None

            if _type not in ["run", "resume"]:
                self.state = SchedulerState.FAILED
                raise SchedulerError(f"AgentHeartbeat unknown command: {_type}")

            _run_id = command.get("run_id")
            if not _run_id:
                self.state = SchedulerState.FAILED
                raise SchedulerError(f"No runId in agent heartbeat: {command}")
            if _run_id in self._runs:
                wandb.termlog(f"{LOG_PREFIX}Skipping duplicate run: {_run_id}")
                continue

            return SweepRun(
                id=_run_id,
                args=command.get("args", {}),
                logs=command.get("logs", []),
                worker_id=worker_id,
            )
        return None

    def _get_sweep_commands(self, worker_id: int) -> List[Dict[str, Any]]:
        """Helper to recieve sweep command from backend."""
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

    def _exit(self) -> None:
        pass

    def _load_state(self) -> None:
        pass

    def _save_state(self) -> None:
        pass
