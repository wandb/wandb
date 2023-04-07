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

    def _poll(self) -> None:
        """Iterate through runs.

        Get state from backend and deletes runs if not in running state. Threadsafe.
        """
        # TODO(gst): move to better constants place
        end_states = ["crashed", "failed", "killed", "finished"]
        run_states = ["running", "pending", "preempted", "preempting"]

        _runs_to_remove: List[str] = []
        for run_id, run in self._yield_runs():
            try:
                _state = self._api.get_run_state(self._entity, self._project, run_id)
                _rqi_state = run.queued_run.state if run.queued_run else None
                if not _state or _state in end_states or _rqi_state == "failed":
                    _logger.debug(
                        f"({run_id}) run-state:{_state}, rqi-state:{_rqi_state}"
                    )
                    run.state = RunState.DEAD
                    _runs_to_remove.append(run_id)
                elif _state in run_states:
                    run.state = RunState.ALIVE
            except CommError as e:
                _logger.debug(
                    f"Issue when getting state for run ({run_id}) with error: {e}"
                )
                run.state = RunState.UNKNOWN
                continue
        # Remove any runs that are dead
        with self._threading_lock:
            for run_id in _runs_to_remove:
                wandb.termlog(f"{LOG_PREFIX}Cleaning up finished run ({run_id})")
                del self._runs[run_id]

    def _exit(self) -> None:
        pass

    def _poll(self) -> None:
        pass

    def _load_state(self) -> None:
        pass

    def _save_state(self) -> None:
        pass
