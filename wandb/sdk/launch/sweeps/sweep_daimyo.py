from dataclasses import dataclass
import os
from enum import Enum
import logging
import pprint
import queue
import socket
import time
import threading
from typing import Any, Dict, Optional

from .daimyo import Daimyo
import wandb
from wandb import wandb_lib
from wandb.errors import SweepError
from wandb.wandb_agent import Agent as LegacySweepAgent


logger = logging.getLogger(__name__)


class SweepRunState(Enum):
    QUEUED = 0
    RUNNING = 1
    STOPPED = 2
    ERRORED = 3
    DONE = 4

@dataclass
class SweepRun:
    command: Dict[str, Any]
    id: str
    state: str = SweepRunState.QUEUED


class SweepDaimyo(Daimyo):
    """A SweepDaimyo is a controller/agent that will populate a Launch RunQueue with
    launch jobs it creates from run suggestions it pulls from an internal sweeps RunQueue.
    """

    def __init__(
        self,
        *args,
        sweep_id: Optional[str] = None,
        sweep_config: Optional[Dict[str, Any]] = None,
        heartbeat_thread_sleep: int = 5,
        heartbeat_queue_timeout: int = 5,
        main_thread_sleep: int = 5,
        **kwargs,
    ):
        super(SweepDaimyo, self).__init__(*args, **kwargs)
        # Make sure the provided sweep_id corresponds to a valid sweep
        found = self._api.sweep(
            sweep_id, "{}", entity=self._entity, project=self._project
        )
        if not found:
            raise SweepError(
                f"Could not find sweep {self._entity}/{self._project}/{sweep_id}"
            )
        self._sweep_id = sweep_id
        # TODO(hupo): Sweep config can also come in through init kwarg? (python usecase)
        # TODO(hupo): Get command from sweep config? (if no local kwarg is provided?)
        # TODO(hupo): Look for sweep config in upserted sweep?
        self._sweep_config = sweep_config
        self._heartbeat_thread_sleep = heartbeat_thread_sleep
        self._heartbeat_queue_timeout = heartbeat_queue_timeout
        self._main_thread_sleep = main_thread_sleep

    def _start(self):
        # Status for all the sweep runs this agent has popped off the sweep runqueue
        self._heartbeat_runs: Dict[str, SweepRun] = {}
        # Mapping from sweep run ids to launch job ids
        self._heartbeat_runs_to_launch_jobs: Dict[str, str] = {}
        # TODO(hupo): socket hostname is probably a shitty name, we can do better
        self._heartbeat_agent = self._api.register_agent(
            socket.gethostname(), sweep_id=self._sweep_id
        )
        self._heartbeat_agent = self._heartbeat_agent["id"]
        # Thread will pop items off the Sweeps RunQueue using AgentHeartbeat
        # and put them in this internal queue, which will be used to populate
        # the Launch RunQueue
        self._heartbeat_queue: "queue.Queue[SweepRun]" = queue.Queue()
        self._heartbeat_thread = threading.Thread(target=self._heartbeat)
        self._heartbeat_thread.daemon = True
        self._heartbeat_thread.start()

    def _heartbeat(self):
        while True:
            # Make sure Daimyo is alive
            if not self.is_alive():
                return
            # AgentHeartbeat wants dict of runs which are running or queued
            _run_states = {}
            for run_id, run in self._heartbeat_runs.items():
                if run.state in [SweepRunState.RUNNING, SweepRunState.QUEUED]:
                    _run_states[run_id] = True
            _msg = f"AgentHeartbeat sending: \n{pprint.pformat(_run_states)}\n"
            logger.debug(_msg)
            wandb.termlog(_msg)
            commands = self._api.agent_heartbeat(self._heartbeat_agent, {}, _run_states)
            if commands:
                _msg = f"AgentHeartbeat received {len(commands)} commands: \n{pprint.pformat(commands)}\n"
                logger.debug(_msg)
                wandb.termlog(_msg)
                for command in commands:
                    _type = command.get("type")
                    _run_id = command.get("run_id")
                    _run = SweepRun(
                        command = command,
                        id = _run_id,
                    )
                    # TODO(hupo): Should a thread be putting dicts into a dict?
                    self._heartbeat_runs[_run_id] = _run
                    if _type in ["run", "resume"]:
                        self._heartbeat_queue.put(_run)
                    elif _type == "stop":
                        self._stop_run(_run_id)
                        continue
                    elif _type == "exit":
                        self._exit()
                        continue
            time.sleep(self._heartbeat_thread_sleep)

    def _run(self):
        try:
            run: SweepRun = self._heartbeat_queue.get(timeout=self._heartbeat_queue_timeout)
        except queue.Empty:
            _msg = "No jobs in Sweeps RunQueue, waiting..."
            logger.debug(_msg)
            wandb.termlog(_msg)
            time.sleep(self._main_thread_sleep)
            return

        # If run is already stopped just ignore the request
        if run.state == SweepRunState.STOPPED:
            return

        # This will cause Anaconda2 to populate the Sweeps RunQueue
        for run_id, run in self._heartbeat_runs.items():
            _msg = f"Current run {run_id} is {run.state}"
            logger.debug(_msg)
            wandb.termlog(_msg)
            if run.state == SweepRunState.RUNNING:
                run.state = SweepRunState.DONE
                _msg = f"Marking run {run_id} as {run.state}"
                logger.debug(_msg)
                wandb.termlog(_msg)

        _msg = f"Converting Sweep RunQueue Item to Launch Job: \n{pprint.pformat(run.command)}\n"
        logger.debug(_msg)
        wandb.termlog(_msg)

        # TODO(hupo): Command replacement logic
        # sweep_command = self._sweep_command or [
        #     "${env}",
        #     "${interpreter}",
        #     "${program}",
        #     "${args}",
        # ]

        # This is actually what populates the wandb config
        # since it is used in wandb.init()
        sweep_param_path = os.path.join(
            os.environ.get(wandb.env.DIR, os.getcwd()),
            "wandb",
            f"sweep-{self._sweep_id}",
            f"config-{run.command['run_id']}.yaml",
        )
        wandb.termlog(f"Saving params to {sweep_param_path}")
        wandb_lib.config_util.save_config_file_from_dict(
            sweep_param_path, run.command["args"]
        )

        entry_point = [
            "python",
            run.command["program"],
        ]

        command_args = LegacySweepAgent._create_command_args(run.command)
        entry_point += command_args["args"]

        # TODO: Entrypoint is now an object right?
        entry_point_str = " ".join(entry_point)
        job = self._add_to_launch_queue(
            {
                "uri": os.getcwd(),
                "resource": "local-process",
                "entry_point": entry_point_str,
                "run_id": run.id,
            }
        )
        run.state = SweepRunState.RUNNING

        # TODO(hupo): Flapping logic
        # elif self._heartbeat_runs_status[run.id] == RunStatus.ERRORED:
        #     exc = self._exceptions[run.id]
        #     logger.error(f"Run {run.id} errored: {repr(exc)}")
        #     wandb.termerror(f"Run {run.id} errored: {repr(exc)}")

        #     if os.getenv(wandb.env.AGENT_DISABLE_FLAPPING) == "true":
        #         self._exit_flag = True
        #         return
        #     elif (
        #         time.time() - self._start_time < self.FLAPPING_MAX_SECONDS
        #     ) and (len(self._exceptions) >= self.FLAPPING_MAX_FAILURES):
        #         msg = "Detected {} failed runs in the first {} seconds, killing sweep.".format(
        #             self.FLAPPING_MAX_FAILURES, self.FLAPPING_MAX_SECONDS
        #         )
        #         logger.error(msg)
        #         wandb.termerror(msg)
        #         wandb.termlog(
        #             "To disable this check set WANDB_AGENT_DISABLE_FLAPPING=true"
        #         )
        #         self._exit_flag = True
        #         return
        #     if (
        #         self._max_initial_failures < len(self._exceptions)
        #         and len(self._exceptions) >= count
        #     ):
        #         msg = "Detected {} failed runs in a row at start, killing sweep.".format(
        #             self._max_initial_failures
        #         )
        #         logger.error(msg)
        #         wandb.termerror(msg)
        #         wandb.termlog(
        #             "To change this value set WANDB_AGENT_MAX_INITIAL_FAILURES=val"
        #         )
        #         self._exit_flag = True
        #         return

    def _stop_run(self, run_id):
        _msg = f"Stopping run {run_id}."
        logger.debug(_msg)
        wandb.termlog(_msg)
        self._heartbeat_runs[run_id].state = SweepRunState.STOPPED
        # TODO(hupo): Can you command the launch agent to kill the associated job?

    def _stop_all_runs(self):
        _msg = "Stopping all runs."
        logger.debug(_msg)
        wandb.termlog(_msg)
        for run_id in self._heartbeat_runs.keys():
            self._stop_run(run_id)

    def _exit(self):
        self._stop_all_runs()
        # TODO(hupo): Send mutation to kill the sweep?
