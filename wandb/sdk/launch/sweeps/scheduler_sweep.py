"""Scheduler for classic wandb Sweeps."""
from dataclasses import dataclass
import logging
import os
import pprint
import queue
import socket
import threading
import time
from typing import Any, Dict, List, Optional

import wandb
from wandb import wandb_lib  # type: ignore
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
    thread: threading.Thread
    stop: threading.Event


class SweepScheduler(Scheduler):
    """A SweepScheduler is a controller/agent that will populate a Launch RunQueue with
    launch jobs it creates from run suggestions it pulls from an internal sweeps RunQueue.
    """

    def __init__(
        self,
        *args: Any,
        sweep_id: Optional[str] = None,
        num_workers: int = 4,
        worker_sleep: float = 0.5,
        heartbeat_queue_timeout: float = 1,
        heartbeat_queue_sleep: float = 1,
        **kwargs: Any,
    ):
        super().__init__(*args, **kwargs)
        # Make sure the provided sweep_id corresponds to a valid sweep
        found = self._api.sweep(
            sweep_id, "{}", entity=self._entity, project=self._project
        )
        if not found:
            raise SchedulerError(
                f"{LOG_PREFIX}Could not find sweep {self._entity}/{self._project}/{sweep_id}"
            )
        self._sweep_id: str = sweep_id
        # Threading is used to run multiple workers in parallel
        self._workers: List[_Worker] = []
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
            self._workers.append(
                _Worker(
                    agent_config=agent_config,
                    agent_id=agent_config["id"],
                    thread=_thread,
                    # Worker threads will be killed with an Event
                    stop=threading.Event(),
                )
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
            # AgentHeartbeat wants dict of runs which are running or queued
            _run_states = {}
            for run_id, run in self._yield_runs():
                # Filter out runs that are from a different worker thread
                if run.worker_id == worker_id and run.state == SimpleRunState.ALIVE:
                    _run_states[run_id] = True
            _msg = (
                f"{LOG_PREFIX}AgentHeartbeat sending: \n{pprint.pformat(_run_states)}\n"
            )
            logger.debug(_msg)
            # TODO(hupo): Should be sub-set of _run_states specific to worker thread
            commands = self._api.agent_heartbeat(
                self._workers[worker_id].agent_id, {}, _run_states
            )
            if commands:
                _msg = f"{LOG_PREFIX}AgentHeartbeat received {len(commands)} commands: \n{pprint.pformat(commands)}\n"
                logger.debug(_msg)
                for command in commands:
                    _type = command.get("type")
                    # type can be one of "run", "resume", "stop", "exit"
                    if _type == "exit":
                        self.state = SchedulerState.COMPLETED
                        self.exit()
                        return
                    if _type == "stop":
                        # TODO(hupo): Debug edge cases while stopping with active runs
                        self.state = SchedulerState.COMPLETED
                        self.exit()
                        return
                    run = SweepRun(
                        id=command.get("run_id"),
                        args=command.get("args"),
                        logs=command.get("logs"),
                        program=command.get("program"),
                    )
                    with self._threading_lock:
                        self._runs[run.id] = run
                    if _type in ["run", "resume"]:
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

    def _stop_run(self, run_id: str) -> None:
        run = self._runs.get(run_id, None)
        if run is not None:
            # Set threading event to stop the worker thread
            if self._workers[run.worker_id].thread.is_alive():
                self._workers[run.worker_id].stop.set()
            run.state = SimpleRunState.DEAD

    def _exit(self) -> None:
        self.state = SchedulerState.COMPLETED
