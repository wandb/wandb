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

import six

import wandb
from wandb.apis import InternalApi
from wandb.wandb_config import Config
from wandb import util
from wandb import wandb_run


logger = logging.getLogger(__name__)


class AgentError(Exception):
    pass


class Agent(object):
    POLL_INTERVAL = 5
    REPORT_INTERVAL = 5
    KILL_DELAY = 30

    def __init__(self, api, queue, sweep_id=None):
        self._api = api
        self._queue = queue
        self._run_processes = {}  # keyed by run.id (GQL run name)
        self._server_responses = []
        self._sweep_id = sweep_id
        self._log = []
        self._running = True
        self._last_report_time = None
        self._report_interval = wandb.env.get_agent_report_interval(self.REPORT_INTERVAL)
        self._kill_delay = wandb.env.get_agent_kill_delay(self.KILL_DELAY)
        if self._report_interval is None:
            raise AgentError("Invalid agent report interval")
        if self._kill_delay is None:
            raise AgentError("Invalid agent kill delay")

    def run(self):
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
                    if run_process.poll() is None:
                        run_status[run_id] = True
                    else:
                        logger.info('Cleaning up dead run: %s', run_id)
                        del self._run_processes[run_id]
                        self._last_report_time = None

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

        self._run_processes[run.id] = subprocess.Popen(
            ['/usr/bin/env', 'python', command['program']] + flags,
            env=env, preexec_fn=os.setpgrp)

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


def run_agent(sweep_id=None):
    logger.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    api = InternalApi()
    queue = multiprocessing.Queue()
    agent = Agent(api, queue, sweep_id=sweep_id)
    agent.run()
