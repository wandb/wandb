import collections
import json
import logging
import multiprocessing
import os
import socket
import subprocess
import sys
import traceback
import time
import signal
import platform

import six
from six.moves import queue
import yaml

import wandb
from wandb.apis import InternalApi
from wandb.wandb_config import Config
from wandb import util
from wandb import wandb_run
from wandb import env


logger = logging.getLogger(__name__)


class AgentError(Exception):
    pass


class AgentProcess(object):
    """Launch and manage a process."""

    def __init__(self, env=None, command=None, function=None, run_id=None, in_jupyter=None):
        self._popen = None
        self._proc = None
        self._finished_q = multiprocessing.Queue()
        self._proc_killed = False

        if command:
            if platform.system() == "Windows":
                kwargs = dict(creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
            else:
                kwargs = dict(preexec_fn=os.setpgrp)
            self._popen = subprocess.Popen(command,
                env=env, **kwargs)
        elif function:
            self._proc = multiprocessing.Process(target=self._start,
                    args=(self._finished_q, env, function, run_id, in_jupyter))
            self._proc.start()
        else:
            raise AgentError("Agent Process requires command or function")

    def _start(self, finished_q, env, function, run_id, in_jupyter):
        if env:
            for k, v in env.items():
                os.environ[k] = v

        # call user function
        print("wandb: Agent Started Run:", run_id)
        if function:
            function()
        print("wandb: Agent Finished Run:", run_id, "\n")

        # complete the run
        run = wandb.run
        if run:
            if in_jupyter:
                run._stop_jupyter_agent()
            else:
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
            # if on windows, wait() will block and we wont be able to interrupt
            if platform.system() == "Windows":
                try:
                    while True:
                        p = self._popen.poll()
                        if p is not None:
                            return p
                        time.sleep(1)
                except KeyboardInterrupt:
                    raise
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


class Agent(object):
    POLL_INTERVAL = 5
    REPORT_INTERVAL = 0
    KILL_DELAY = 30
    FLAPPING_MAX_SECONDS = 60
    FLAPPING_MAX_FAILURES = 3

    def __init__(self, api, queue, sweep_id=None, function=None, in_jupyter=None, count=None):
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
        self._report_interval = wandb.env.get_agent_report_interval(self.REPORT_INTERVAL)
        self._kill_delay = wandb.env.get_agent_kill_delay(self.KILL_DELAY)
        self._finished = 0
        self._failed = 0
        self._count = count
        self._sweep_command = []
        if self._report_interval is None:
            raise AgentError("Invalid agent report interval")
        if self._kill_delay is None:
            raise AgentError("Invalid agent kill delay")

    def is_flapping(self):
        """Flapping occurs if the agents receives FLAPPING_MAX_FAILURES non-0
            exit codes in the first FLAPPING_MAX_SECONDS"""
        if os.getenv(env.AGENT_DISABLE_FLAPPING) == "true":
            return False
        if time.time() < wandb.START_TIME + self.FLAPPING_MAX_SECONDS:
            return self._failed >= self.FLAPPING_MAX_FAILURES

    def run(self):

        # TODO: catch exceptions, handle errors, show validation warnings, and make more generic
        sweep_obj = self._api.sweep(self._sweep_id, "{}")
        if sweep_obj:
            sweep_yaml = sweep_obj.get('config')
            if sweep_yaml:
                sweep_config = yaml.safe_load(sweep_yaml)
                if sweep_config:
                    sweep_command = sweep_config.get('command')
                    if sweep_command and isinstance(sweep_command, list):
                        self._sweep_command = sweep_command

        # TODO: include sweep ID
        agent = self._api.register_agent(
            socket.gethostname(), sweep_id=self._sweep_id)
        agent_id = agent['id']

        try:
            while self._running:
                commands = util.read_many_from_queue(
                    self._queue, 100, self.POLL_INTERVAL)
                for command in commands:
                    command['resp_queue'].put(self._process_command(command))

                now = util.stopwatch_now()
                if self._last_report_time is None or (self._report_interval != 0 and
                                                      now > self._last_report_time + self._report_interval):
                    logger.info('Running runs: %s', list(
                        self._run_processes.keys()))
                    self._last_report_time = now
                run_status = {}
                for run_id, run_process in list(six.iteritems(self._run_processes)):
                    poll_result = run_process.poll()
                    if poll_result is None:
                        run_status[run_id] = True
                        continue
                    elif not isinstance(poll_result, bool) and isinstance(poll_result, int) and poll_result > 0:
                        self._failed += 1
                        if self.is_flapping():
                            logger.error("Detected %i failed runs in the first %i seconds, shutting down.", self.FLAPPING_MAX_FAILURES, self.FLAPPING_MAX_SECONDS)
                            logger.info("To disable this check set WANDB_AGENT_DISABLE_FLAPPING=true")
                            self._running = False
                            break
                    logger.info('Cleaning up finished run: %s', run_id)
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
                    self._server_responses.append(
                        self._process_command(command))

        except KeyboardInterrupt:
            try:
                wandb.termlog(
                    'Ctrl-c pressed. Waiting for runs to end. Press ctrl-c again to terminate them.')
                for run_id, run_process in six.iteritems(self._run_processes):
                    run_process.wait()
            except KeyboardInterrupt:
                pass
        finally:
            try:
                if not self._in_jupyter:
                    wandb.termlog(
                        'Terminating and syncing runs. Press ctrl-c to kill.')
                for run_id, run_process in six.iteritems(self._run_processes):
                    try:
                        run_process.terminate()
                    except OSError:
                        pass  # if process is already dead
                for run_id, run_process in six.iteritems(self._run_processes):
                    run_process.wait()
            except KeyboardInterrupt:
                wandb.termlog('Killing runs and quitting.')
                for run_id, run_process in six.iteritems(self._run_processes):
                    try:
                        run_process.kill()
                    except OSError:
                        pass  # if process is already dead

    def _process_command(self, command):
        logger.info('Agent received command: %s' %
                    (command['type'] if 'type' in command else 'Unknown'))
        response = {
            'id': command.get('id'),
            'result': None,
        }
        try:
            command_type = command['type']
            result = None
            if command_type == 'run':
                result = self._command_run(command)
            elif command_type == 'stop':
                result = self._command_stop(command)
            elif command_type == 'exit':
                result = self._command_exit(command)
            else:
                raise AgentError('No such command: %s' % command_type)
            response['result'] = result
        except:
            logger.exception('Exception while processing command: %s', command)
            ex_type, ex, tb = sys.exc_info()
            response['exception'] = '{}: {}'.format(ex_type.__name__, str(ex))
            response['traceback'] = traceback.format_tb(tb)
            del tb

        self._log.append((command, response))

        return response

    def _command_run(self, command):
        logger.info('Agent starting run with config:\n' +
                    '\n'.join(['\t{}: {}'.format(k, v['value']) for k, v in command['args'].items()]))
        if self._in_jupyter:
            print('wandb: Agent Starting Run: {} with config:\n'.format(command.get('run_id'))  +
                    '\n'.join(['\t{}: {}'.format(k, v['value']) for k, v in command['args'].items()]))

        run = wandb_run.Run(mode='run',
                            sweep_id=self._sweep_id,
                            storage_id=command.get('run_storage_id'),
                            run_id=command.get('run_id'))

        # save the the wandb config to reflect the state of the run that the
        # the server generated.
        run.config.set_run_dir(run.dir)
        run.config.update({k: v['value'] for k, v in command['args'].items()})

        env = dict(os.environ)
        sweep_env = command.get('env', {})
        env.update(sweep_env)
        run.set_environment(env)

        flags = ["--{}={}".format(name, config['value'])
                 for name, config in command['args'].items()]

        if self._function:
            proc = AgentProcess(function=self._function, env=env,
                    run_id=command.get('run_id'), in_jupyter=self._in_jupyter)
        else:
            sweep_vars = dict(interpreter=["python"], program=[command['program']], args=flags, env=["/usr/bin/env"])
            if platform.system() == "Windows":
                del sweep_vars["env"]
            command_list = []
            sweep_command = self._sweep_command or ["${env}", "${interpreter}", "${program}", "${args}"]
            for c in sweep_command:
                c = str(c)
                if c.startswith("${") and c.endswith("}"):
                    replace_list = sweep_vars.get(c[2:-1])
                    command_list += replace_list or []
                else:
                    command_list += [c]
            logger.info('About to run command: {}'.format(' '.join(command_list)))
            proc = AgentProcess(command=command_list, env=env)
        self._run_processes[run.id] = proc

        # we keep track of when we sent the sigterm to give processes a chance
        # to handle the signal before sending sigkill every heartbeat
        self._run_processes[run.id].last_sigterm_time = None
        self._last_report_time = None

    def _command_stop(self, command):
        run_id = command['run_id']
        if run_id in self._run_processes:
            proc = self._run_processes[run_id]
            now = util.stopwatch_now()
            if proc.last_sigterm_time is None:
                proc.last_sigterm_time = now
                logger.info('Stop: %s', run_id)
                try:
                    proc.terminate()
                except OSError:  # if process is already dead
                    pass
            elif now > proc.last_sigterm_time + self._kill_delay:
                logger.info('Kill: %s', run_id)
                try:
                    proc.kill()
                except OSError:  # if process is already dead
                    pass
        else:
            logger.error('Run %s not running', run_id)

    def _command_exit(self, command):
        logger.info('Received exit command. Killing runs and quitting.')
        for run_id, proc in six.iteritems(self._run_processes):
            try:
                proc.kill()
            except OSError:
                # process is already dead
                pass
        self._running = False

class AgentApi(object):
    def __init__(self, queue):
        self._queue = queue
        self._command_id = 0
        self._multiproc_manager = multiprocessing.Manager()

    def command(self, command):
        command['origin'] = 'local'
        command['id'] = 'local-%s' % self._command_id
        self._command_id += 1
        resp_queue = self._multiproc_manager.Queue()
        command['resp_queue'] = resp_queue
        self._queue.put(command)
        result = resp_queue.get()
        print('result:', result)
        if 'exception' in result:
            print('Exception occurred while running command')
            for line in result['traceback']:
                print(line.strip())
            print(result['exception'])
        return result

def run_agent(sweep_id, function=None, in_jupyter=None, entity=None, project=None, count=None):
    parts = dict(entity=entity, project=project, name=sweep_id)
    err = util.parse_sweep_id(parts)
    if err:
        wandb.termerror(err)
        return
    entity = parts.get("entity") or entity
    project = parts.get("project") or project
    sweep_id = parts.get("name") or sweep_id

    if entity:
        env.set_entity(entity)
    if project:
        env.set_project(project)
    logger.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    log_level = logging.DEBUG
    if in_jupyter:
        log_level = logging.ERROR
    ch.setLevel(log_level)
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    ch.setFormatter(formatter)
    try:
        logger.addHandler(ch)

        api = InternalApi()
        queue = multiprocessing.Queue()
        agent = Agent(api, queue, sweep_id=sweep_id, function=function, in_jupyter=in_jupyter, count=count)
        agent.run()
    finally:
        # make sure we remove the logging handler (important for jupyter notebooks)
        logger.removeHandler(ch)


def agent(sweep_id, function=None, entity=None, project=None, count=None):
    """Generic agent entrypoint, used for CLI or jupyter.

    Args:
        sweep_id (dict): Sweep ID generated by CLI or sweep API
        entity (str, optional): W&B Entity
        project (str, optional): W&B Project
        function (dict, optional): Configure sweep function
    """
    in_jupyter = wandb._get_python_type() != "python"
    if in_jupyter:
        os.environ[env.JUPYTER] = "true"
        _api0 = InternalApi()
        if not _api0.api_key:
            wandb._jupyter_login(api=_api0)
    return run_agent(sweep_id, function=function, in_jupyter=in_jupyter, entity=entity, project=project, count=count)
