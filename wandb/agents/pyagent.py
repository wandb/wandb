"""Agent - Agent object.

Manage wandb agent.

"""

import ctypes
import logging
import os
import queue
import socket
import threading
import time
import traceback

import wandb
from wandb.apis import InternalApi
from wandb.sdk.launch.sweeps import utils as sweep_utils

logger = logging.getLogger(__name__)


def _terminate_thread(thread):
    if not thread.is_alive():
        return
    if hasattr(thread, "_terminated"):
        return
    thread._terminated = True
    tid = getattr(thread, "_thread_id", None)
    if tid is None:
        for k, v in threading._active.items():
            if v is thread:
                tid = k
    if tid is None:
        # This should never happen
        return
    logger.debug(f"Terminating thread: {tid}")
    res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
        ctypes.c_long(tid), ctypes.py_object(Exception)
    )
    if res == 0:
        # This should never happen
        return
    elif res != 1:
        # Revert
        logger.debug(f"Termination failed for thread {tid}")
        ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(tid), None)


class Job:
    def __init__(self, command):
        self.command = command
        job_type = command.get("type")
        self.type = job_type
        self.run_id = command.get("run_id")
        self.config = command.get("args")

    def __repr__(self):
        if self.type == "run":
            return f"Job({self.run_id},{self.config})"
        elif self.type == "stop":
            return f"stop({self.run_id})"
        else:
            return "exit"


class RunStatus:
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    ERRORED = "ERRORED"
    DONE = "DONE"


class Agent:
    FLAPPING_MAX_SECONDS = 60
    FLAPPING_MAX_FAILURES = 3
    MAX_INITIAL_FAILURES = 5

    def __init__(
        self, sweep_id=None, project=None, entity=None, function=None, count=None
    ):
        self._sweep_path = sweep_id
        self._sweep_id = None
        self._project = project
        self._entity = entity
        self._function = function
        self._count = count
        # glob_config = os.path.expanduser('~/.config/wandb/settings')
        # loc_config = 'wandb/settings'
        # files = (glob_config, loc_config)
        self._api = InternalApi()
        self._agent_id = None
        self._max_initial_failures = wandb.env.get_agent_max_initial_failures(
            self.MAX_INITIAL_FAILURES
        )
        # if the directory to log to is not set, set it
        if os.environ.get(wandb.env.DIR) is None:
            os.environ[wandb.env.DIR] = os.path.abspath(os.getcwd())

    def _init(self):
        # These are not in constructor so that Agent instance can be rerun
        self._run_threads = {}
        self._run_status = {}
        self._queue = queue.Queue()
        self._exit_flag = False
        self._exceptions = {}
        self._start_time = time.time()

    def _register(self):
        logger.debug("Agent._register()")
        agent = self._api.register_agent(socket.gethostname(), sweep_id=self._sweep_id)
        self._agent_id = agent["id"]
        logger.debug(f"agent_id = {self._agent_id}")

    def _setup(self):
        logger.debug("Agent._setup()")
        self._init()
        parts = dict(entity=self._entity, project=self._project, name=self._sweep_path)
        err = sweep_utils.parse_sweep_id(parts)
        if err:
            wandb.termerror(err)
            return
        entity = parts.get("entity") or self._entity
        project = parts.get("project") or self._project
        sweep_id = parts.get("name") or self._sweep_id
        if sweep_id:
            os.environ[wandb.env.SWEEP_ID] = sweep_id
        if entity:
            wandb.env.set_entity(entity)
        if project:
            wandb.env.set_project(project)
        if sweep_id:
            self._sweep_id = sweep_id
        self._register()

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
        # _terminate_thread(self._main_thread)

    def _heartbeat(self):
        while True:
            if self._exit_flag:
                return
            # if not self._main_thread.is_alive():
            #     return
            run_status = {
                run: True
                for run, status in self._run_status.items()
                if status in (RunStatus.QUEUED, RunStatus.RUNNING)
            }
            commands = self._api.agent_heartbeat(self._agent_id, {}, run_status)
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

    def _run_jobs_from_queue(self):  # noqa:C901
        global _INSTANCES
        _INSTANCES += 1
        try:
            waiting = False
            count = 0
            while True:
                if self._exit_flag:
                    return
                try:
                    try:
                        job = self._queue.get(timeout=5)
                        if self._exit_flag:
                            logger.debug("Exiting main loop due to exit flag.")
                            wandb.termlog("Sweep Agent: Exiting.")
                            return
                    except queue.Empty:
                        if not waiting:
                            logger.debug("Paused.")
                            wandb.termlog("Sweep Agent: Waiting for job.")
                            waiting = True
                        time.sleep(5)
                        if self._exit_flag:
                            logger.debug("Exiting main loop due to exit flag.")
                            wandb.termlog("Sweep Agent: Exiting.")
                            return
                        continue
                    if waiting:
                        logger.debug("Resumed.")
                        wandb.termlog("Job received.")
                        waiting = False
                    count += 1
                    run_id = job.run_id
                    if self._run_status[run_id] == RunStatus.STOPPED:
                        continue
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
                        exc_type, exc_value, exc_traceback = (
                            exc.__class__,
                            exc,
                            exc.__traceback__,
                        )
                        exc_traceback_formatted = traceback.format_exception(
                            exc_type, exc_value, exc_traceback
                        )
                        exc_repr = "".join(exc_traceback_formatted)
                        logger.error(f"Run {run_id} errored:\n{exc_repr}")
                        wandb.termerror(f"Run {run_id} errored:\n{exc_repr}")
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
                except KeyboardInterrupt:
                    logger.debug("Ctrl + C detected. Stopping sweep.")
                    wandb.termlog("Ctrl + C detected. Stopping sweep.")
                    self._exit()
                    return
                except Exception as e:
                    if self._exit_flag:
                        logger.debug("Exiting main loop due to exit flag.")
                        wandb.termlog("Sweep Agent: Killed.")
                        return
                    else:
                        raise e
        finally:
            _INSTANCES -= 1

    def _run_job(self, job):
        try:
            run_id = job.run_id

            config_file = os.path.join(
                "wandb", "sweep-" + self._sweep_id, "config-" + run_id + ".yaml"
            )
            os.environ[wandb.env.RUN_ID] = run_id
            base_dir = os.environ.get(wandb.env.DIR, "")
            sweep_param_path = os.path.join(base_dir, config_file)
            os.environ[wandb.env.SWEEP_PARAM_PATH] = sweep_param_path
            wandb.wandb_lib.config_util.save_config_file_from_dict(
                sweep_param_path, job.config
            )
            os.environ[wandb.env.SWEEP_ID] = self._sweep_id
            wandb.teardown()

            wandb.termlog(f"Agent Starting Run: {run_id} with config:")
            for k, v in job.config.items():
                wandb.termlog("\t{}: {}".format(k, v["value"]))

            self._function()
            wandb.finish()
        except KeyboardInterrupt as ki:
            raise ki
        except Exception as e:
            wandb.finish(exit_code=1)
            if self._run_status[run_id] == RunStatus.RUNNING:
                self._run_status[run_id] = RunStatus.ERRORED
                self._exceptions[run_id] = e
        finally:
            # clean up the environment changes made
            os.environ.pop(wandb.env.RUN_ID, None)
            os.environ.pop(wandb.env.SWEEP_ID, None)
            os.environ.pop(wandb.env.SWEEP_PARAM_PATH, None)

    def run(self):
        logger.info(
            "Starting sweep agent: entity={}, project={}, count={}".format(
                self._entity, self._project, self._count
            )
        )
        self._setup()
        # self._main_thread = threading.Thread(target=self._run_jobs_from_queue)
        self._heartbeat_thread = threading.Thread(target=self._heartbeat)
        self._heartbeat_thread.daemon = True
        # self._main_thread.start()
        self._heartbeat_thread.start()
        # self._main_thread.join()
        self._run_jobs_from_queue()


def pyagent(sweep_id, function, entity=None, project=None, count=None):
    """Generic agent entrypoint, used for CLI or jupyter.

    Args:
        sweep_id (dict): Sweep ID generated by CLI or sweep API
        function (func, optional): A function to call instead of the "program"
        entity (str, optional): W&B Entity
        project (str, optional): W&B Project
        count (int, optional): the number of trials to run.
    """
    if not callable(function):
        raise Exception("function parameter must be callable!")
    agent = Agent(
        sweep_id,
        function=function,
        entity=entity,
        project=project,
        count=count,
    )
    agent.run()


_INSTANCES = 0


def is_running():
    return bool(_INSTANCES)
