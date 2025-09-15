import logging
import multiprocessing
import os
import platform
import queue
import re
import signal
import socket
import subprocess
import sys
import time
import traceback
from typing import Any, Callable, Dict, List, Optional

import yaml

import wandb
from wandb import util, wandb_lib, wandb_sdk
from wandb.agents.pyagent import pyagent
from wandb.apis import InternalApi
from wandb.sdk.launch.sweeps import utils as sweep_utils
from wandb.sdk.lib import ipython

logger = logging.getLogger(__name__)


class AgentError(Exception):
    pass


class AgentProcess:
    """Launch and manage a process."""

    def __init__(
        self, env=None, command=None, function=None, run_id=None, in_jupyter=None
    ):
        self._popen = None
        self._proc = None
        self._finished_q = multiprocessing.Queue()
        self._proc_killed = False

        if command:
            if platform.system() == "Windows":
                kwargs = dict(creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
                env.pop(wandb.env.SERVICE, None)
                # TODO: Determine if we need the same stdin workaround as POSIX case below.
                self._popen = subprocess.Popen(command, env=env, **kwargs)
            else:
                if sys.version_info >= (3, 11):
                    # preexec_fn=os.setpgrp is not thread-safe; process_group was introduced in
                    # python 3.11 to replace it, so use that when possible
                    kwargs = dict(process_group=0)
                else:
                    kwargs = dict(preexec_fn=os.setpgrp)
                env.pop(wandb.env.SERVICE, None)
                # Upon spawning the subprocess in a new process group, the child's process group is
                # not connected to the controlling terminal's stdin. If it tries to access stdin,
                # it gets a SIGTTIN and blocks until we give it the terminal, which we don't want
                # to do.
                #
                # By using subprocess.PIPE, we give it an independent stdin. However, it will still
                # block if it tries to read from stdin, because we're not writing anything to it.
                # We immediately close the subprocess's stdin here so it can fail fast and get an
                # EOF.
                #
                # (One situation that makes this relevant is that importing `readline` even
                # indirectly can cause the child to attempt to access stdin, which can trigger the
                # deadlock. In Python 3.13, `import torch` indirectly imports `readline` via `pdb`,
                # meaning `import torch` in a run script can deadlock unless we override stdin.
                # See https://github.com/wandb/wandb/pull/10489 description for more details.)
                #
                # Also, we avoid spawning a new session because that breaks preempted child process
                # handling.
                self._popen = subprocess.Popen(
                    command,
                    env=env,
                    stdin=subprocess.PIPE,
                    **kwargs,
                )
                self._popen.stdin.close()
        elif function:
            self._proc = multiprocessing.Process(
                target=self._start,
                args=(self._finished_q, env, function, run_id, in_jupyter),
            )
            self._proc.start()
        else:
            raise AgentError("Agent Process requires command or function")

    def _start(self, finished_q, env, function, run_id, in_jupyter):
        if env:
            for k, v in env.items():
                os.environ[k] = v

        # call user function
        wandb.termlog(f"Agent Started Run: {run_id}")
        if function:
            function()
        wandb.termlog(f"Agent Finished Run: {run_id}\n")

        # complete the run
        run = wandb.run
        if run:
            wandb.join()

        # signal that the process is finished
        finished_q.put(True)

    def poll(self):
        if self._popen:
            return self._popen.poll()
        if self._proc_killed:
            # we need to join process to prevent zombies
            self._proc.join()
            return True
        try:
            finished = self._finished_q.get(False, 0)
            if finished:
                return True
        except queue.Empty:
            pass
        return

    def wait(self):
        if self._popen:
            # if on windows, wait() will block and we won't be able to interrupt
            if platform.system() == "Windows":
                while True:
                    p = self._popen.poll()
                    if p is not None:
                        return p
                    time.sleep(1)
            return self._popen.wait()
        return self._proc.join()

    def kill(self):
        if self._popen:
            return self._popen.kill()
        pid = self._proc.pid
        if pid:
            ret = os.kill(pid, signal.SIGKILL)
            self._proc_killed = True
            return ret
        return

    def terminate(self):
        if self._popen:
            # windows terminate is too strong, send Ctrl-C instead
            if platform.system() == "Windows":
                return self._popen.send_signal(signal.CTRL_C_EVENT)
            return self._popen.terminate()
        return self._proc.terminate()


class Agent:
    POLL_INTERVAL = 5
    REPORT_INTERVAL = 0
    KILL_DELAY = 30
    FLAPPING_MAX_SECONDS = 60
    FLAPPING_MAX_FAILURES = 3
    MAX_INITIAL_FAILURES = 5
    DEFAULT_SWEEP_COMMAND: List[str] = [
        "${env}",
        "${interpreter}",
        "${program}",
        "${args}",
    ]
    SWEEP_COMMAND_ENV_VAR_REGEX = re.compile(r"\$\{envvar\:([A-Z0-9_]*)\}")

    def __init__(
        self, api, queue, sweep_id=None, function=None, in_jupyter=None, count=None
    ):
        self._api = api
        self._queue = queue
        self._run_processes = {}  # keyed by run.id (GQL run name)
        self._server_responses = []
        self._sweep_id = sweep_id
        self._in_jupyter = in_jupyter
        self._log = []
        self._running = True
        self._last_report_time = None
        self._function = function
        self._report_interval = wandb.env.get_agent_report_interval(
            self.REPORT_INTERVAL
        )
        self._kill_delay = wandb.env.get_agent_kill_delay(self.KILL_DELAY)
        self._finished = 0
        self._failed = 0
        self._count = count
        self._sweep_command = []
        self._max_initial_failures = wandb.env.get_agent_max_initial_failures(
            self.MAX_INITIAL_FAILURES
        )
        if self._report_interval is None:
            raise AgentError("Invalid agent report interval")
        if self._kill_delay is None:
            raise AgentError("Invalid agent kill delay")
        # if the directory to log to is not set, set it
        if os.environ.get("WANDB_DIR") is None:
            os.environ["WANDB_DIR"] = os.path.abspath(os.getcwd())

    def is_flapping(self):
        """Determine if the process is flapping.

        Flapping occurs if the agents receives FLAPPING_MAX_FAILURES non-0 exit codes in
        the first FLAPPING_MAX_SECONDS.
        """
        if os.getenv(wandb.env.AGENT_DISABLE_FLAPPING) == "true":
            return False
        if time.time() < wandb.START_TIME + self.FLAPPING_MAX_SECONDS:
            return self._failed >= self.FLAPPING_MAX_FAILURES

    def is_failing(self):
        return (
            self._failed >= self._finished
            and self._max_initial_failures <= self._failed
        )

    def run(self):  # noqa: C901
        # TODO: catch exceptions, handle errors, show validation warnings, and make more generic
        sweep_obj = self._api.sweep(self._sweep_id, "{}")
        if sweep_obj:
            sweep_yaml = sweep_obj.get("config")
            if sweep_yaml:
                sweep_config = yaml.safe_load(sweep_yaml)
                if sweep_config:
                    sweep_command = sweep_config.get("command")
                    if sweep_command and isinstance(sweep_command, list):
                        self._sweep_command = sweep_command

        # TODO: include sweep ID
        agent = self._api.register_agent(socket.gethostname(), sweep_id=self._sweep_id)
        agent_id = agent["id"]

        try:
            while self._running:
                commands = util.read_many_from_queue(
                    self._queue, 100, self.POLL_INTERVAL
                )
                for command in commands:
                    command["resp_queue"].put(self._process_command(command))

                now = util.stopwatch_now()
                if self._last_report_time is None or (
                    self._report_interval != 0
                    and now > self._last_report_time + self._report_interval
                ):
                    logger.info("Running runs: %s", list(self._run_processes.keys()))
                    self._last_report_time = now
                run_status = {}
                for run_id, run_process in list(self._run_processes.items()):
                    poll_result = run_process.poll()
                    if poll_result is None:
                        run_status[run_id] = True
                        continue
                    elif (
                        not isinstance(poll_result, bool)
                        and isinstance(poll_result, int)
                        and poll_result > 0
                    ):
                        self._failed += 1
                        if self.is_flapping():
                            logger.error(
                                "Detected %i failed runs in the first %i seconds, shutting down.",
                                self.FLAPPING_MAX_FAILURES,
                                self.FLAPPING_MAX_SECONDS,
                            )
                            logger.info(
                                "To disable this check set WANDB_AGENT_DISABLE_FLAPPING=true"
                            )
                            self._running = False
                            break
                        if self.is_failing():
                            logger.error(
                                "Detected %i failed runs in a row, shutting down.",
                                self._max_initial_failures,
                            )
                            logger.info(
                                "To change this value set WANDB_AGENT_MAX_INITIAL_FAILURES=val"
                            )
                            self._running = False
                            break
                    logger.info("Cleaning up finished run: %s", run_id)

                    # wandb.teardown() was added with wandb service and is a hammer to make
                    # sure that active runs are finished before moving on to another agent run
                    #
                    # In the future, a lighter weight way to implement this could be to keep a
                    # service process open for all the agent instances and inform_finish when
                    # the run should be marked complete.  This however could require
                    # inform_finish on every run created by this process.
                    if hasattr(wandb, "teardown"):
                        exit_code = 0
                        if isinstance(poll_result, int):
                            exit_code = poll_result
                        elif isinstance(poll_result, bool):
                            exit_code = -1
                        wandb.teardown(exit_code)

                    del self._run_processes[run_id]
                    self._last_report_time = None
                    self._finished += 1

                if self._count and self._finished >= self._count or not self._running:
                    self._running = False
                    continue

                commands = self._api.agent_heartbeat(agent_id, {}, run_status)

                # TODO: send _server_responses
                self._server_responses = []
                for command in commands:
                    self._server_responses.append(self._process_command(command))

        except KeyboardInterrupt:
            try:
                wandb.termlog(
                    "Ctrl-c pressed. Waiting for runs to end. Press ctrl-c again to terminate them."
                )
                for _, run_process in self._run_processes.items():
                    run_process.wait()
            except KeyboardInterrupt:
                pass
        finally:
            try:
                if not self._in_jupyter:
                    wandb.termlog("Terminating and syncing runs. Press ctrl-c to kill.")
                for _, run_process in self._run_processes.items():
                    try:
                        run_process.terminate()
                    except OSError:
                        pass  # if process is already dead
                for _, run_process in self._run_processes.items():
                    run_process.wait()
            except KeyboardInterrupt:
                wandb.termlog("Killing runs and quitting.")
                for _, run_process in self._run_processes.items():
                    try:
                        run_process.kill()
                    except OSError:
                        pass  # if process is already dead

    def _process_command(self, command):
        logger.info(
            "Agent received command: %s"
            % (command["type"] if "type" in command else "Unknown")
        )
        response = {
            "id": command.get("id"),
            "result": None,
        }
        try:
            command_type = command["type"]
            if command_type == "run":
                result = self._command_run(command)
            elif command_type == "stop":
                result = self._command_stop(command)
            elif command_type == "exit":
                result = self._command_exit(command)
            elif command_type == "resume":
                result = self._command_run(command)
            else:
                raise AgentError(f"No such command: {command_type}")  # noqa: TRY301
            response["result"] = result
        except Exception:
            logger.exception("Exception while processing command: %s", command)
            ex_type, ex, tb = sys.exc_info()
            response["exception"] = f"{ex_type.__name__}: {str(ex)}"
            response["traceback"] = traceback.format_tb(tb)
            del tb

        self._log.append((command, response))

        return response

    def _command_run(self, command):
        logger.info(
            "Agent starting run with config:\n"
            + "\n".join(
                ["\t{}: {}".format(k, v["value"]) for k, v in command["args"].items()]
            )
        )
        if self._in_jupyter:
            wandb.termlog(
                f"Agent Starting Run: {command.get('run_id')} with config:\n"
                + "\n".join(
                    [f"\t{k}: {v['value']}" for k, v in command["args"].items()]
                )
            )

        # Setup sweep command
        sweep_command: List[str] = sweep_utils.create_sweep_command(self._sweep_command)

        run_id = command.get("run_id")
        sweep_id = os.environ.get(wandb.env.SWEEP_ID)
        # TODO(jhr): move into settings
        config_file = os.path.join(
            "wandb", "sweep-" + sweep_id, "config-" + run_id + ".yaml"
        )
        json_file = os.path.join(
            "wandb", "sweep-" + sweep_id, "config-" + run_id + ".json"
        )

        os.environ[wandb.env.RUN_ID] = run_id

        base_dir = os.environ.get(wandb.env.DIR, "")
        sweep_param_path = os.path.join(base_dir, config_file)
        os.environ[wandb.env.SWEEP_PARAM_PATH] = sweep_param_path
        wandb_lib.config_util.save_config_file_from_dict(
            sweep_param_path, command["args"]
        )

        env = dict(os.environ)

        sweep_vars: Dict[str, Any] = sweep_utils.create_sweep_command_args(command)

        if "${args_json_file}" in sweep_command:
            with open(json_file, "w") as fp:
                fp.write(sweep_vars["args_json"][0])

        if self._function:
            # make sure that each run regenerates setup singleton
            wandb.teardown()
            proc = AgentProcess(
                function=self._function,
                env=env,
                run_id=run_id,
                in_jupyter=self._in_jupyter,
            )
        else:
            sweep_vars["interpreter"] = ["python"]
            sweep_vars["program"] = [command["program"]]
            sweep_vars["args_json_file"] = [json_file]
            if not platform.system() == "Windows":
                sweep_vars["env"] = ["/usr/bin/env"]
            command_list = []
            for c in sweep_command:
                c = str(c)
                if c.startswith("${") and c.endswith("}"):
                    replace_list = sweep_vars.get(c[2:-1])
                    command_list += replace_list or []
                else:
                    command_list += [c]
            logger.info(
                "About to run command: {}".format(
                    " ".join(f'"{c}"' if " " in c else c for c in command_list)
                )
            )
            proc = AgentProcess(command=command_list, env=env)
        self._run_processes[run_id] = proc

        # we keep track of when we sent the sigterm to give processes a chance
        # to handle the signal before sending sigkill every heartbeat
        self._run_processes[run_id].last_sigterm_time = None
        self._last_report_time = None

    def _command_stop(self, command):
        run_id = command["run_id"]
        if run_id in self._run_processes:
            proc = self._run_processes[run_id]
            now = util.stopwatch_now()
            if proc.last_sigterm_time is None:
                proc.last_sigterm_time = now
                logger.info("Stop: %s", run_id)
                try:
                    proc.terminate()
                except OSError:  # if process is already dead
                    pass
            elif now > proc.last_sigterm_time + self._kill_delay:
                logger.info("Kill: %s", run_id)
                try:
                    proc.kill()
                except OSError:  # if process is already dead
                    pass
        else:
            logger.error("Run %s not running", run_id)

    def _command_exit(self, command):
        logger.info("Received exit command. Killing runs and quitting.")
        for _, proc in self._run_processes.items():
            try:
                proc.kill()
            except OSError:
                # process is already dead
                pass
        self._running = False


class AgentApi:
    def __init__(self, queue):
        self._queue = queue
        self._command_id = 0
        self._multiproc_manager = multiprocessing.Manager()

    def command(self, command):
        command["origin"] = "local"
        command["id"] = f"local-{self._command_id}"
        self._command_id += 1
        resp_queue = self._multiproc_manager.Queue()
        command["resp_queue"] = resp_queue
        self._queue.put(command)
        result = resp_queue.get()
        print("result:", result)  # noqa: T201
        if "exception" in result:
            print("Exception occurred while running command")  # noqa: T201
            for line in result["traceback"]:
                print(line.strip())  # noqa: T201
            print(result["exception"])  # noqa: T201
        return result


def run_agent(
    sweep_id, function=None, in_jupyter=None, entity=None, project=None, count=None
):
    parts = dict(entity=entity, project=project, name=sweep_id)
    err = sweep_utils.parse_sweep_id(parts)
    if err:
        wandb.termerror(err)
        return
    entity = parts.get("entity") or entity
    project = parts.get("project") or project
    sweep_id = parts.get("name") or sweep_id

    if entity:
        wandb.env.set_entity(entity)
    if project:
        wandb.env.set_project(project)
    if sweep_id:
        # TODO(jhr): remove when jobspec is merged
        os.environ[wandb.env.SWEEP_ID] = sweep_id
    logger.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    log_level = logging.DEBUG
    if in_jupyter:
        log_level = logging.ERROR
    ch.setLevel(log_level)
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    ch.setFormatter(formatter)
    try:
        logger.addHandler(ch)

        api = InternalApi()
        queue = multiprocessing.Queue()
        agent = Agent(
            api,
            queue,
            sweep_id=sweep_id,
            function=function,
            in_jupyter=in_jupyter,
            count=count,
        )
        agent.run()
    finally:
        # make sure we remove the logging handler (important for jupyter notebooks)
        logger.removeHandler(ch)


def agent(
    sweep_id: str,
    function: Optional[Callable] = None,
    entity: Optional[str] = None,
    project: Optional[str] = None,
    count: Optional[int] = None,
) -> None:
    """Start one or more sweep agents.

    The sweep agent uses the `sweep_id` to know which sweep it
    is a part of, what function to execute, and (optionally) how
    many agents to run.

    Args:
        sweep_id: The unique identifier for a sweep. A sweep ID
            is generated by W&B CLI or Python SDK.
        function: A function to call instead of the "program"
            specified in the sweep config.
        entity: The username or team name where you want to send W&B
            runs created by the sweep to. Ensure that the entity you
            specify already exists. If you don't specify an entity,
            the run will be sent to your default entity,
            which is usually your username.
        project: The name of the project where W&B runs created from
            the sweep are sent to. If the project is not specified, the
            run is sent to a project labeled "Uncategorized".
        count: The number of sweep config trials to try.
    """
    global _INSTANCES
    _INSTANCES += 1
    try:
        # make sure we are logged in
        wandb_sdk.wandb_login._login(_silent=True)
        if function:
            return pyagent(sweep_id, function, entity, project, count)
        return run_agent(
            sweep_id,
            function=function,
            in_jupyter=ipython.in_jupyter(),
            entity=entity,
            project=project,
            count=count,
        )
    finally:
        _INSTANCES -= 1


_INSTANCES = 0


def _is_running():
    return bool(_INSTANCES)
