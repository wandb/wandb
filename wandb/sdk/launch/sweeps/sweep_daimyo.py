import os
import logging
import pprint
import queue
import socket
import time
import threading
from typing import Any, Dict, Optional

from .daimyo import Daimyo
import wandb
from wandb.wandb_agent import Agent as LegacySweepAgent


logger = logging.getLogger(__name__)


class LegacySweepCommand:
    """ Legacy Sweep Command. """

    # State must match Go's RunState
    # TODO: Link file in core
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    ERRORED = "ERRORED"
    DONE = "DONE"

    def __init__(self, command: Dict[str, Any]):
        self.command = command
        self.type = command.get("type")
        self.id = command.get("run_id")


class SweepDaimyo(Daimyo):
    """A SweepDaimyo is a controller/agent that will populate a Launch RunQueue with
    launch jobs it pulls from an internal sweeps RunQueue.
    """

    def __init__(
        self,
        *args,
        sweep_id: Optional[str] = None,
        sweep_config: Optional[Dict[str, Any]] = None,
        **kwargs,
    ):
        super(SweepDaimyo, self).__init__(*args, **kwargs)
        # TODO: verify these properties, throw errors
        # TODO: Get command from sweep config? (if no local kwarg is provided?)
        # TODO: Look for sweep config in upserted sweep?
        # TODO: Sweep config can also come in through init kwarg? (python usecase)
        self._sweep_id = sweep_id
        self._sweep_config = sweep_config

    def _start(self):
        # Status for all the sweep runs this agent has popped off the sweep runqueue
        self._heartbeat_runs_status: Dict[str, LegacySweepCommand] = {}
        # Mapping from sweep run ids to launch job ids
        self._heartbeat_runs_to_launch_jobs: Dict[str, str] = {}
        # TODO: socket hostname is probably a shitty name, we can do better
        self._heartbeat_agent = self._api.register_agent(
            socket.gethostname(), sweep_id=self._sweep_id
        )
        self._heartbeat_agent = self._heartbeat_agent["id"]
        # Thread will pop items off the Sweeps RunQueue using AgentHeartbeat
        # and put them in this internal queue, which will be used to populate
        # the Launch RunQueue
        self._heartbeat_queue: "queue.Queue[LegacySweepCommand]" = queue.Queue()
        self._heartbeat_thread = threading.Thread(target=self._heartbeat)
        self._heartbeat_thread.daemon = True
        self._heartbeat_thread.start()

    def _heartbeat(self):
        while True:
            if not self.is_alive():
                return
            run_status = {
                run: True
                for run, status in self._heartbeat_runs_status.items()
                if status in (LegacySweepCommand.QUEUED, LegacySweepCommand.RUNNING)
            }
            commands = self._api.agent_heartbeat(self._heartbeat_agent, {}, run_status)
            if commands:
                run = LegacySweepCommand(commands[0])
                if run.type in ["run", "resume"]:
                    self._heartbeat_queue.put(run)
                    self._heartbeat_runs_status[run.id] = LegacySweepCommand.QUEUED
                elif run.type == "stop":
                    self._stop_run(run.id)
                    continue
                elif run.type == "exit":
                    self._exit()
                    continue
            time.sleep(5)

    def _run(self):
        while True:
            if not self.is_alive():
                return
            try:
                run = self._heartbeat_queue.get(timeout=5)
            except queue.Empty:
                _msg = "No jobs in Sweeps RunQueue, waiting..."
                logger.debug(_msg)
                wandb.termlog(_msg)
                time.sleep(5)
                continue
            _msg = f"Sweep RunQueue AgentHeartbeat received: \n{pprint.pformat(run.command)}\n"
            logger.debug(_msg)
            wandb.termlog(_msg)
            if self._heartbeat_runs_status[run.id] == LegacySweepCommand.STOPPED:
                continue

            entry_point = [
                "python",
                run.command["program"],
            ]
            
            command_args = LegacySweepAgent._create_command_args(run.command)
            entry_point += command_args["args"]

            job = self._add_to_launch_queue({
                "uri": os.getcwd(),
                "resource" : "local-process",
                "entry_point" : entry_point,
            })
            _msg = f"Pushing item from Sweep Run {run.id} to Launch RunQueue as {job._run_id}."
            logger.debug(_msg)
            wandb.termlog(_msg)

            # TODO: Should we tell sweep runqueue that items are running
            #       if they are queued in launch runqueue? Or only if they
            #       are running in launch runqueue?
            self._heartbeat_runs_status[run.id] = LegacySweepCommand.RUNNING

            # if self._heartbeat_runs_status[run.id] == RunStatus.RUNNING:
            #     self._heartbeat_runs_status[run.id] = RunStatus.DONE

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

    # def _stop_run(self, run_id):
    #     logger.debug(f"Stopping run {run_id}.")
    #     self._heartbeat_runs_status[run_id] = LegacySweepCommand.STOPPED
    #     # TODO: Convert run key to job key?
    #     _job = self._jobs.get(run_id)
    #     if _job is not None:
    #         # TODO: Can you command a launch agent to kill a job?
    #         _job.kill()

    # def _stop_all_runs(self):
    #     logger.debug("Stopping all runs.")
    #     for run in list(self._jobs.keys()):
    #         self._stop_run(run)
        
    #     # send mutation to kill the sweep

    def _exit(self):
        pass
    #     self._stop_all_runs()
