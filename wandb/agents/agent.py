# -*- coding: utf-8 -*-
"""Agent - Agent object.

Manage wandb agent.

"""

from __future__ import print_function

import ctypes
import logging
import os
import socket
import threading
import time

from six.moves import queue
import wandb
from wandb import util
from wandb import wandb_sdk
from wandb.apis import InternalApi
from wandb.lib import config_util


logger = logging.getLogger(__name__)


def _terminate_thread(thread):
    if not thread.isAlive():
        return
    tid = getattr(thread, "_thread_id", None)
    if tid is None:
        for k, v in threading._active.items():
            if v is thread:
                tid = k
    if tid is None:
        # This should never happen
        return
    logger.info("Terminating thread: {}".format(tid))
    res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
        ctypes.c_long(tid), ctypes.py_object(Exception)
    )
    if res == 0:
        # This should never happen
        return
    elif res != 1:
        # Revert
        logger.info("Termination failed for thread {}".format(tid))
        ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(tid), None)


class Job(object):
    def __init__(self, command):
        self.command = command
        job_type = command.get("type")
        self.type = job_type
        self.run_id = command.get("run_id")
        self.config = command.get("args")

    def __repr__(self):
        if self.type == "run":
            return "Job({},{})".format(self.run_id, self.config)
        elif self.type == "stop":
            return "stop({})".format(self.run_id)
        else:
            return "exit"


class Agent(object):

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
        self._run_threads = {}
        self._queue = queue.Queue()
        self._stopped_runs = set()
        self._exit_flag = False
        self._stop_flag = False

    def _register(self):
        logger.info("Agent._register()")
        agent = self._api.register_agent(socket.gethostname(), sweep_id=self._sweep_id)
        self._agent_id = agent["id"]
        logger.info("agent_id = {}".format(self._agent_id))

    def _setup(self):
        logger.info("Agent._setup()")
        parts = dict(entity=self._entity, project=self._project, name=self._sweep_path)
        err = util.parse_sweep_id(parts)
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

    def _run_status(self):
        run_status = {}
        dead_runs = []
        for k, v in self._run_threads.items():
            if v.isAlive():
                run_status[k] = True
            else:
                dead_runs.append(k)
        # clean up dead runs
        for k in dead_runs:
            del self._run_threads[k]
        return run_status

    def _stop_run(self, run_id):
        logger.info("Stopping run {}.".format(run_id))
        self._stopped_runs.add(run_id)
        thread = self._run_threads.get(run_id)
        if thread:
            _terminate_thread(thread)
            del self._run_threads[run_id]

    def _stop_all_runs(self):
        logger.info("Stopping all runs.")
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
            # if not self._main_thread.isAlive():
            #     return
            commands = self._api.agent_heartbeat(self._agent_id, {}, self._run_status())
            if not commands:
                continue
            job = Job(commands[0])
            logger.info("Job received: {}".format(job))
            if job.type == "run":
                self._queue.put(job)
            elif job.type == "stop":
                self._stop_flag = True
                self._stop_run(job.run_id)
            elif job.type == "exit":
                self._exit()
                return
            time.sleep(2)

    def _run_jobs_from_queue(self):
        waiting = False
        count = 0
        while True:
            if self._exit_flag:
                return
            try:
                try:
                    job = self._queue.get(timeout=5)
                    if self._exit_flag:
                        logger.info("Exiting main loop due to exit flag.")
                        wandb.termlog("Sweep killed.")
                        return
                except queue.Empty:
                    if self._stop_flag:
                        logger.info("Exiting main loop due to stop flag.")
                        wandb.termlog("Sweep stoped.")
                        return
                    if not waiting:
                        logger.info("Paused.")
                        wandb.termlog("Waiting for job...")
                        waiting = True
                    time.sleep(5)
                    if self._exit_flag:
                        logger.info("Exiting main loop due to exit flag.")
                        wandb.termlog("Sweep killed.")
                        return
                    continue
                if waiting:
                    logger.info("Resumed.")
                    wandb.termlog("Job received.")
                    waiting = False
                count += 1
                logger.info("Spawning new thread for run {}.".format(job.run_id))
                thread = threading.Thread(target=self._run_job, args=(job,))
                self._run_threads[job.run_id] = thread
                thread.start()
                thread.join()
                logger.info("Thread joined for run {}.".format(job.run_id))
                del self._run_threads[job.run_id]
                if self._count and self._count == count:
                    logger.info("Exiting main loop because max count reached.")
                    self._exit_flag = True
                    return
            except KeyboardInterrupt:
                logger.info("Ctrl + C detected. Stopping sweep.")
                wandb.termlog("Ctrl + C detected. Stopping sweep.")
                self._exit()
                return
            except Exception as e:
                if self._exit_flag:
                    logger.info("Exiting main loop due to exit flag.")
                    wandb.termlog("Sweep killed.")
                    return
                else:
                    raise e

    def _run_job(self, job):
        try:
            run_id = job.run_id

            config_file = os.path.join(
                "wandb", "sweep-" + self._sweep_id, "config-" + run_id + ".yaml"
            )
            config_util.save_config_file_from_dict(config_file, job.config)
            os.environ[wandb.env.RUN_ID] = run_id
            os.environ[wandb.env.CONFIG_PATHS] = config_file
            os.environ[wandb.env.SWEEP_ID] = self._sweep_id
            wandb_sdk.wandb_setup._setup(_reset=True)

            print(
                "wandb: Agent Starting Run: {} with config:\n".format(run_id)
                + "\n".join(
                    ["\t{}: {}".format(k, v["value"]) for k, v in job.config.items()]
                )
            )
            self._function()
            if wandb.run:
                wandb.join()
        except KeyboardInterrupt as ki:
            raise ki
        except Exception as e:
            if run_id in self._stopped_runs:
                self._stopped_runs.remove(run_id)
                # wandb.termlog("Stopping run: " + str(run_id))
            else:
                wandb.termerror("Error running job: " + str(e))

    def run(self):
        logger.info("Starting sweep agent: entity={}, project={}, count={}".format(self._entity, self._project, self._count))
        self._exit_flag = False
        self._stop_flag = False
        self._setup()
        # self._main_thread = threading.Thread(target=self._run_jobs_from_queue)
        self._heartbeat_thread = threading.Thread(target=self._heartbeat, daemon=True)
        # self._main_thread.start()
        self._heartbeat_thread.start()
        # self._main_thread.join()
        self._run_jobs_from_queue()


def agent(sweep_id, function, entity=None, project=None, count=None):
    """Generic agent entrypoint, used for CLI or jupyter.

    Args:
        sweep_id (dict): Sweep ID generated by CLI or sweep API
        function (func, optional): A function to call instead of the "program"
        entity (str, optional): W&B Entity
        project (str, optional): W&B Project
        count (int, optional): the number of trials to run.
    """
    if not callable(function):
        raise Exception("function paramter must be callable!")
    agent = Agent(
        sweep_id, function=function, entity=entity, project=project, count=count,
    )
    agent.run()
