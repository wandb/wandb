"""Scheduler for classic wandb Sweeps."""

import logging
from pprint import pformat as pf
from typing import Any, Dict, List, Optional

import wandb
from wandb.sdk.launch.sweeps.scheduler import LOG_PREFIX, RunState, Scheduler, SweepRun

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
        is alive, or None and set the appropriate scheduler state:

        FAILED: self.fail_sweep()
        STOPPED: self.stop_sweep()
        """
        commands: List[Dict[str, Any]] = self._get_sweep_commands(worker_id)
        for command in commands:
            # The command "type" can be one of "run", "resume", "stop", "exit"
            _type = command.get("type")
            if _type in ["exit", "stop"]:
                self.stop_sweep()
                return None

            if _type not in ["run", "resume"]:
                self.fail_sweep(f"AgentHeartbeat unknown command: {_type}")

            _run_id: Optional[str] = command.get("run_id")
            if not _run_id:
                self.fail_sweep(f"No run id in agent heartbeat: {command}")
                return None

            if _run_id in self._runs:
                wandb.termlog(f"{LOG_PREFIX}Skipping duplicate run: {_run_id}")
                continue

            return SweepRun(
                id=_run_id,
                state=RunState.PENDING,
                args=command.get("args", {}),
                logs=command.get("logs", []),
                worker_id=worker_id,
            )
        return None

    def _get_sweep_commands(self, worker_id: int) -> List[Dict[str, Any]]:
        """Helper to receive sweep command from backend."""
        # AgentHeartbeat wants a Dict of runs which are running or queued
        _run_states: Dict[str, bool] = {}
        for run_id, run in self._yield_runs():
            # Filter out runs that are from a different worker thread
            if run.worker_id == worker_id and run.state.is_alive:
                _run_states[run_id] = True

        _logger.debug(f"Sending states: \n{pf(_run_states)}\n")
        commands: List[Dict[str, Any]] = self._api.agent_heartbeat(
            agent_id=self._workers[worker_id].agent_id,
            metrics={},
            run_states=_run_states,
        )
        _logger.debug(f"AgentHeartbeat commands: \n{pf(commands)}\n")

        return commands

    def _exit(self) -> None:
        pass

    def _poll(self) -> None:
        _logger.debug(f"_poll. _runs: {self._runs}")

    def _load_state(self) -> None:
        pass

    def _save_state(self) -> None:
        pass
