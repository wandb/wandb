"""Scheduler for classic wandb Sweeps."""
from dataclasses import dataclass
import logging
import os
import pprint
import queue
import socket
import threading
import time
from typing import Any, Dict, List

import wandb
from wandb import wandb_lib  # type: ignore
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
    thread: threading.Thread
    stop: threading.Event


class SweepScheduler(Scheduler):
    """A SweepScheduler is a controller/agent that will populate a Launch RunQueue with
    launch jobs it creates from run suggestions it pulls from an internal sweeps RunQueue.
    """

    def __init__(
        self,
        *args: Any,
        num_workers: int = 4,
        worker_sleep: float = 0.1,
        heartbeat_queue_timeout: float = 0.1,
        heartbeat_queue_sleep: float = 0.1,
        **kwargs: Any,
    ):
        super().__init__(*args, **kwargs)
        # Threading is used to run multiple workers in parallel. Workers do not
        # actually run training workloads, they simply send heartbeat messages
        # (emulating a real agent) and add new runs to the launch queue. The
        # launch agent is the one that actually runs the training workloads.
        self._workers: Dict[int, _Worker] = {}
        self._num_workers: int = num_workers
        self._worker_sleep: float = worker_sleep
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
            # Worker threads call heartbeat function
            _thread = threading.Thread(target=self._heartbeat, args=[worker_id])
            _thread.daemon = True
            self._workers[worker_id] = _Worker(
                agent_config=agent_config,
                agent_id=agent_config["id"],
                thread=_thread,
                # Worker threads will be killed with an Event
                stop=threading.Event(),
            )
            _thread.start()

    def _heartbeat(self, worker_id: int) -> None:
        while True:
            # Make sure Scheduler is alive
            if not self.is_alive():
                return
            # Check to see if worker thread has been orderred to stop
            if self._workers[worker_id].stop.is_set():
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
                    _type = command.get("type")
                    if _type in ["exit", "stop"]:
                        # Tell (virtual) agent to stop running
                        self.exit()
                        return
                    if _type in ["run", "resume"]:
                        run = SweepRun(
                            id=command.get("run_id", "empty-run-id"),
                            args=command.get("args", {}),
                            logs=command.get("logs", []),
                            program=command.get("program"),
                            worker_id=worker_id,
                        )
                        self._runs[run.id] = run
                        self._heartbeat_queue.put(run)
                        continue
            time.sleep(self._worker_sleep)

    def _run(self) -> None:
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
        # This is actually what populates the wandb config
        # since it is used in wandb.init()
        sweep_param_path = os.path.join(
            os.environ.get(wandb.env.DIR, os.getcwd()),
            "wandb",
            f"sweep-{self._sweep_id}",
            f"config-{run.id}.yaml",
        )
        wandb.termlog(f"{LOG_PREFIX}Saving params to {sweep_param_path}")
        wandb_lib.config_util.save_config_file_from_dict(sweep_param_path, run.args)
        # Construct entry point using legacy sweeps utilities
        command_args = LegacySweepAgent._create_command_args({"args": run.args})["args"]
        entry_point = ["python", run.program] + command_args
        _ = self._add_to_launch_queue(
            entry_point=entry_point,
            run_id=run.id,
        )

    def _kill_worker(self, worker_id: int) -> None:
        _worker = self._workers.get(worker_id, None)
        if _worker and _worker.thread.is_alive():
            # Set threading event to stop the worker thread
            _worker.stop.set()
            print(f"{LOG_PREFIX}Killing AgentHeartbeat worker {worker_id}")
            _worker.thread.join()
            print(f"{LOG_PREFIX}AgentHeartbeat worker {worker_id} killed")

    def _exit(self) -> None:
        self.state = SchedulerState.COMPLETED
