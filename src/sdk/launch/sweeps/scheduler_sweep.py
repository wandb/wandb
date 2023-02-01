"""Scheduler for classic wandb Sweeps."""
import logging
import pprint
import queue
import socket
import time
from dataclasses import dataclass
from typing import Any, Dict, List

import wandb
from wandb.sdk.launch.sweeps import SchedulerError
from wandb.sdk.launch.sweeps.scheduler import (
    LOG_PREFIX,
    Scheduler,
    SchedulerState,
    SimpleRunState,
    SweepRun,
)
from wandb.wandb_agent import Agent as LegacySweepAgent

logger = logging.getLogger(__name__)


@dataclass
class _Worker:
    agent_config: Dict[str, Any]
    agent_id: str


class SweepScheduler(Scheduler):
    """A SweepScheduler is a controller/agent that will populate a Launch RunQueue with
    launch jobs it creates from run suggestions it pulls from an internal sweeps RunQueue.
    """

    def __init__(
        self,
        *args: Any,
        num_workers: int = 8,
        heartbeat_queue_timeout: float = 1.0,
        heartbeat_queue_sleep: float = 1.0,
        **kwargs: Any,
    ):
        super().__init__(*args, **kwargs)
        # Optionally run multiple workers in (pseudo-)parallel. Workers do not
        # actually run training workloads, they simply send heartbeat messages
        # (emulating a real agent) and add new runs to the launch queue. The
        # launch agent is the one that actually runs the training workloads.
        self._workers: Dict[int, _Worker] = {}
        self._num_workers: int = num_workers
        # Thread will pop items off the Sweeps RunQueue using AgentHeartbeat
        # and put them in this internal queue, which will be used to populate
        # the Launch RunQueue
        self._heartbeat_queue: "queue.Queue[SweepRun]" = queue.Queue()
        self._heartbeat_queue_timeout: float = heartbeat_queue_timeout
        self._heartbeat_queue_sleep: float = heartbeat_queue_sleep

    def _start(self) -> None:
        for worker_id in range(self._num_workers):
            logger.debug(f"{LOG_PREFIX}Starting AgentHeartbeat worker {worker_id}\n")
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

    def _heartbeat(self, worker_id: int) -> None:
        # Make sure Scheduler is alive
        if not self.is_alive():
            return
        # AgentHeartbeat wants a Dict of runs which are running or queued
        _run_states: Dict[str, bool] = {}
        for run_id, run in self._yield_runs():
            # Filter out runs that are from a different worker thread
            if run.worker_id == worker_id and run.state == SimpleRunState.ALIVE:
                _run_states[run_id] = True
        logger.debug(
            f"{LOG_PREFIX}AgentHeartbeat sending: \n{pprint.pformat(_run_states)}\n"
        )
        commands: List[Dict[str, Any]] = self._api.agent_heartbeat(
            self._workers[worker_id].agent_id,  # agent_id: str
            {},  # metrics: dict
            _run_states,  # run_states: dict
        )
        logger.debug(
            f"{LOG_PREFIX}AgentHeartbeat received {len(commands)} commands: \n{pprint.pformat(commands)}\n"
        )
        if commands:
            for command in commands:
                # The command "type" can be one of "run", "resume", "stop", "exit"
                _type = command.get("type", None)
                if _type in ["exit", "stop"]:
                    # Tell (virtual) agent to stop running
                    self.state = SchedulerState.STOPPED
                    self.exit()
                    return
                elif _type in ["run", "resume"]:
                    _run_id = command.get("run_id", None)
                    if _run_id is None:
                        self.state = SchedulerState.FAILED
                        raise SchedulerError(
                            f"AgentHeartbeat command {command} missing run_id"
                        )
                    if _run_id in self._runs:
                        wandb.termlog(f"{LOG_PREFIX} Skipping duplicate run {run_id}")
                    else:
                        run = SweepRun(
                            id=_run_id,
                            args=command.get("args", {}),
                            logs=command.get("logs", []),
                            program=command.get("program", None),
                            worker_id=worker_id,
                        )
                        self._runs[run.id] = run
                        self._heartbeat_queue.put(run)
                else:
                    self.state = SchedulerState.FAILED
                    raise SchedulerError(f"AgentHeartbeat unknown command type {_type}")

    def _run(self) -> None:
        # Go through all workers and heartbeat
        for worker_id in self._workers.keys():
            self._heartbeat(worker_id)
        try:
            run: SweepRun = self._heartbeat_queue.get(
                timeout=self._heartbeat_queue_timeout
            )
        except queue.Empty:
            wandb.termlog(f"{LOG_PREFIX}No jobs in Sweeps RunQueue, waiting...")
            time.sleep(self._heartbeat_queue_sleep)
            return
        # If run is already stopped just ignore the request
        if run.state in [
            SimpleRunState.DEAD,
            SimpleRunState.UNKNOWN,
        ]:
            return
        wandb.termlog(
            f"{LOG_PREFIX}Converting Sweep Run (RunID:{run.id}) to Launch Job"
        )
        _ = self._add_to_launch_queue(
            run_id=run.id,
            entry_point=["python3", run.program] if run.program else None,
            # Use legacy sweep utilities to extract args dict from agent heartbeat run.args
            config={
                "overrides": {
                    "run_config": LegacySweepAgent._create_command_args(
                        {"args": run.args}
                    )["args_dict"]
                }
            },
        )

    def _exit(self) -> None:
        pass
