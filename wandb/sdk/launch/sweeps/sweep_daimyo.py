import os
import logging
import queue
import socket
import time
import threading
from typing import Any, Dict, Optional

from .daimyo import Daimyo, DaimyoState
import wandb
from wandb.wandb_agent import Agent as LegacySweepAgent


logger = logging.getLogger(__name__)

class LegacySweepRun:
    """ Legacy Sweep Run . """

    # State must match Go's RunStatus
    # TODO: Link in code
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    ERRORED = "ERRORED"
    DONE = "DONE"

    def __init__(self, command: Dict[str, Any]):
        self.type = command.get("type")
        self.id = command.get("run_id")
        self.config = command.get("args", {})


class SweepDaimyo(Daimyo):
    """ A SweepDaimyo is a controller/agent that will populate a Launch RunQueue with
    launch jobs it pulls from an internal sweeps RunQueue.
    """

    def _start(self):
        # TODO: socket hostname is probably a shitty name, we can do better
        self._heartbeat_agent = self._api.register_agent(socket.gethostname(), sweep_id=self._sweep_id)
        self._heartbeat_agent = self._heartbeat_agent["id"]
        self._heartbeat_runs_status: Dict[str, LegacySweepRun] = {}
        self._heartbeat_queue: "queue.Queue[LegacySweepRun]" = queue.Queue()
        self._heartbeat_thread = threading.Thread(target=self._heartbeat)
        self._heartbeat_thread.daemon = True
        # TODO: Get command from sweep config? (if no local kwarg is provided?)
        # TODO: Look for sweep config in upserted sweep?
        # TODO: Sweep config can also come in through init kwarg? (python usecase)


    def _heartbeat(self):
        while True:
            if not self.is_alive():
                return
            run_status = {
                run: True
                for run, status in self._heartbeat_runs_status.items()
                if status in (LegacySweepRun.QUEUED, LegacySweepRun.RUNNING)
            }
            commands = self._api.agent_heartbeat(self._heartbeat_agent, {}, run_status)
            breakpoint()
            if commands:
                run = LegacySweepRun(commands[0])
                if run.type in ["run", "resume"]:
                    self._heartbeat_queue.put(run)
                    self._heartbeat_runs_status[run.id] = LegacySweepRun.QUEUED
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
                sweep_run = self._heartbeat_queue.get(timeout=5)
            except queue.Empty:
                _msg = "No jobs in Sweeps RunQueue, waiting..."
                logger.debug(_msg)
                wandb.termlog(_msg)
                time.sleep(5)
                continue
            _msg = f"Sweep RunQueue job received: {job}"
            logger.debug(_msg)
            wandb.termlog(_msg)
            if self._heartbeat_runs_status[sweep_run.run_id] == LegacySweepRun.STOPPED:
                continue

            breakpoint()

            # TODO  - Send job to launch agent
            run_spec = {

            }
            job = self._add_to_launch_queue(run_spec)
            _msg = f"Pushing item from Sweep Run {sweep_run.run_id} to Launch RunQueue as {job._run_id}."
            logger.debug(_msg)
            wandb.termlog(_msg)

            # TODO: Should we tell sweep runqueue that items are running
            #       if they are queued in launch runqueue? Or only if they
            #       are running in launch runqueue?
            self._heartbeat_runs_status[sweep_run.run_id] = LegacySweepRun.RUNNING
        

            # if self._heartbeat_runs_status[sweep_run.run_id] == RunStatus.RUNNING:
            #     self._heartbeat_runs_status[sweep_run.run_id] = RunStatus.DONE

            # elif self._heartbeat_runs_status[sweep_run.run_id] == RunStatus.ERRORED:
            #     exc = self._exceptions[sweep_run.run_id]
            #     logger.error(f"Run {run_id} errored: {repr(exc)}")
            #     wandb.termerror(f"Run {run_id} errored: {repr(exc)}")

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
        logger.debug(f"Stopping run {run_id}.")
        self._heartbeat_runs_status[run_id] = LegacySweepRun.STOPPED
        # TODO: Convert run key to job key
        _job = self._jobs.get(run_id)
        if _job is not None:
            # TODO: Can you command a launch agent to kill a job?
            _job.kill()

    def _stop_all_runs(self):
        logger.debug("Stopping all runs.")
        for run in list(self._jobs.keys()):
            self._stop_run(run)

    def _exit(self):
        self._stop_all_runs()

    def _convert_legacy_sweep_runspec(self, launch_spec: Dict[str, Any]) -> None:
        # breakpoint()
        if launch_spec.get("uri") is not None:
            # Not a legacy sweep RunSpec
            return
        logger.info("Legacy Sweep runSpec detected. Converting to Launch RunSpec format")
        launch_spec["uri"] = os.getcwd()  # TODO: This seems hacky...
        launch_spec["entity"] = self._entity
        launch_spec["project"] = self._project
        # For now sweep runs use local process backend
        launch_spec["resource"] = "local-process"
        sweep_id = self._queues[0]
        launch_spec["overrides"] = {
            "args": ["--count", "1"],
            "entry_point": f"wandb agent {self._entity}/{self._project}/{sweep_id}",
            # "resource_args" : {}
        }
        # legacy_args = LegacySweepAgent._create_command_args(launch_spec)['args']
        # if legacy_args:
        #     launch_spec["overrides"]["args"].extend(legacy_args)
        # Remove old legacy RunSpec fields
        del launch_spec["args"]
        del launch_spec["logs"]
