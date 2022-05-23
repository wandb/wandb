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
from wandb.agents.pyagent import RunStatus, Job

logger = logging.getLogger(__name__)


class SweepDaimyo(Daimyo):
    """ A SweepDaimyo is a controller/agent that will populate a Launch RunQueue with
    launch jobs it pulls from an internal sweeps RunQueue.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sweep_agent: Optional[str] = None

    def _start(self):
        # TODO: socket hostname is probably a shitty name, we can do better
        _agent = self._api.register_agent(socket.gethostname(), sweep_id=self._sweep_id)
        self._sweep_agent = _agent["id"]
        self._run_status = {}
        self._queue = queue.Queue()
        self._heartbeat_thread = threading.Thread(target=self._heartbeat)
        self._heartbeat_thread.daemon = True
        # TODO: Get command from sweep config? (if no local kwarg is provided?)
        # TODO: Look for sweep config in upserted sweep?
        # TODO: Sweep config can also come in through init kwarg? (python usecase)

    def _heartbeat(self):
        while True:
            if self.state in [
                DaimyoState.COMPLETED,
                DaimyoState.FAILED,
                DaimyoState.CANCELLED,
            ]:
                return
            run_status = {
                run: True
                for run, status in self._run_status.items()
                if status in (RunStatus.QUEUED, RunStatus.RUNNING)
            }
            commands = self._api.agent_heartbeat(self._sweep_agent, {}, run_status)
            if commands:
                job = Job(commands[0])
                logger.debug(f"Job received: {job}")
                if job.type in ["run", "resume"]:
                    self._queue.put(job)
                    self._run_status[job.run_id] = RunStatus.QUEUED
                elif job.type == "stop":
                    self._stop_run(job.run_id)
                elif job.type == "exit":
                    self._exit()
                    return
            time.sleep(5)

    def _run(self):
        while True:
            if self.state in [
                DaimyoState.COMPLETED,
                DaimyoState.FAILED,
                DaimyoState.CANCELLED,
            ]:
                return
            try:
                job = self._queue.get(timeout=5)
            except queue.Empty:
                _msg = "No jobs in Sweeps RunQueue, waiting..."
                logger.debug(_msg)
                wandb.termlog(_msg)
                time.sleep(5)
                continue
            _msg = f"Sweep RunQueue job received: {job}"
            logger.debug(_msg)
            wandb.termlog(_msg)
            run_id = job.run_id
            if self._run_status[run_id] == RunStatus.STOPPED:
                continue

            # TODO  - Send job to launch agent

            self._run_threads[run_id] = thread
            thread.start()
            self._run_status[run_id] = RunStatus.RUNNING
        
        logger.debug(f"Spawning new thread for run {run_id}.")
        thread = threading.Thread(target=self._run_job, args=(job,))
        self._run_threads[run_id] = thread
        thread.start()
        self._run_status[run_id] = RunStatus.RUNNING
        thread.join()
        logger.debug(f"Thread joined for run {run_id}.")
        if self._run_status[run_id] == RunStatus.RUNNING:
            self._run_status[run_id] = RunStatus.DONE
        elif self._run_status[run_id] == RunStatus.ERRORED:
            exc = self._exceptions[run_id]
            logger.error(f"Run {run_id} errored: {repr(exc)}")
            wandb.termerror(f"Run {run_id} errored: {repr(exc)}")
            if os.getenv(wandb.env.AGENT_DISABLE_FLAPPING) == "true":
                self._exit_flag = True
                return
            elif (
                time.time() - self._start_time < self.FLAPPING_MAX_SECONDS
            ) and (len(self._exceptions) >= self.FLAPPING_MAX_FAILURES):
                msg = "Detected {} failed runs in the first {} seconds, killing sweep.".format(
                    self.FLAPPING_MAX_FAILURES, self.FLAPPING_MAX_SECONDS
                )
                logger.error(msg)
                wandb.termerror(msg)
                wandb.termlog(
                    "To disable this check set WANDB_AGENT_DISABLE_FLAPPING=true"
                )
                self._exit_flag = True
                return
            if (
                self._max_initial_failures < len(self._exceptions)
                and len(self._exceptions) >= count
            ):
                msg = "Detected {} failed runs in a row at start, killing sweep.".format(
                    self._max_initial_failures
                )
                logger.error(msg)
                wandb.termerror(msg)
                wandb.termlog(
                    "To change this value set WANDB_AGENT_MAX_INITIAL_FAILURES=val"
                )
                self._exit_flag = True
                return
        if self._count and self._count == count:
            logger.debug("Exiting main loop because max count reached.")
            self._exit_flag = True
            return

    def _stop_run(self, run_id):
        logger.debug(f"Stopping run {run_id}.")
        self._run_status[run_id] = RunStatus.STOPPED
        thread = self._run_threads.get(run_id)
        if thread:
            _terminate_thread(thread)

    def _stop_all_runs(self):
        logger.debug("Stopping all runs.")
        for run in list(self._run_threads.keys()):
            self._stop_run(run)

    def _exit(self):
        self._stop_all_runs()
        self._exit_flag = True

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
