from dataclasses import dataclass
import os
import logging
import pprint
import queue
import socket
import time
import threading
from typing import Any, Dict, Optional

from .daimyo import Daimyo, SweepRun, RunState
import wandb
from wandb import wandb_lib
from wandb.errors import SweepError
from wandb.wandb_agent import Agent as LegacySweepAgent


logger = logging.getLogger(__name__)


class SweepDaimyo(Daimyo):
    """A SweepDaimyo is a controller/agent that will populate a Launch RunQueue with
    launch jobs it creates from run suggestions it pulls from an internal sweeps RunQueue.
    """

    def __init__(
        self,
        *args,
        sweep_id: Optional[str] = None,
        sweep_config: Optional[Dict[str, Any]] = None,
        heartbeat_thread_sleep: int = 3,
        heartbeat_queue_timeout: int = 3,
        main_thread_sleep: int = 3,
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
            for run_id, run in self._runs.items():
                if run.state in [RunState.RUNNING, RunState.QUEUED]:
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
                    run = SweepRun(
                        id=command.get("run_id"),
                        args=command.get("args"),
                        logs=command.get("logs"),
                        program=command.get("program"),
                    )
                    self._runs[run.id] = run
                    if _type in ["run", "resume"]:
                        self._heartbeat_queue.put(run)
                    elif _type == "stop":
                        self._stop_run(run.id)
                        continue
                    elif _type == "exit":
                        self._exit()
                        continue
            time.sleep(self._heartbeat_thread_sleep)

    def _run(self):
        try:
            run: SweepRun = self._heartbeat_queue.get(
                timeout=self._heartbeat_queue_timeout
            )
        except queue.Empty:
            _msg = "No jobs in Sweeps RunQueue, waiting..."
            logger.debug(_msg)
            wandb.termlog(_msg)
            time.sleep(self._main_thread_sleep)
            return

        # If run is already stopped just ignore the request
        if run.state in [
            RunState.STOPPED,
            RunState.STOPPED,
            RunState.ERRORED,
            RunState.DONE,
            RunState.UNKNOWN,
        ]:
            return

        _msg = f"Converting Sweep Run (RunID:{run.id}) to Launch Job"
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
            f"config-{run.id}.yaml",
        )
        wandb.termlog(f"Saving params to {sweep_param_path}")
        wandb_lib.config_util.save_config_file_from_dict(sweep_param_path, run.args)

        entry_point = ["python", run.program]

        command_args = LegacySweepAgent._create_command_args({"args": run.args})
        entry_point += command_args["args"]

        # TODO: Entrypoint is now an object right?
        entry_point_str = " ".join(entry_point)
        self._add_to_launch_queue(
            {
                "uri": os.getcwd(),
                "resource": "local-process",
                "entry_point": entry_point_str,
                "run_id": run.id,
            }
        )

        # TODO(hupo): Flapping logic

    def _exit(self):
        pass
