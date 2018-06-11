import collections
import json
import logging
import multiprocessing
import os
import socket
import subprocess
import sys
import traceback

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

    def __init__(self, api, queue, sweep_id=None):
        self._api = api
        self._queue = queue
        self._run_processes = {}  # keyed by run.id (GQL run name)
        self._server_responses = []
        self._sweep_id = sweep_id
        self._log = []

    def run(self):
        # TODO: include sweep ID
        agent = self._api.register_agent(
            socket.gethostname(), True, sweep_id=self._sweep_id)
        agent_id = agent['id']

        try:
            while True:
                commands = util.read_many_from_queue(
                    self._queue, 100, self.POLL_INTERVAL)
                for command in commands:
                    command['resp_queue'].put(self._process_command(command))

                logger.info('Running runs: %s', list(
                    self._run_processes.keys()))
                run_status = {}
                for run_id, run_process in list(six.iteritems(self._run_processes)):
                    if run_process.poll() is None:
                        run_status[run_id] = True
                    else:
                        logger.info('Cleaning up dead run: %s', run_id)
                        del self._run_processes[run_id]

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
        logger.info('Agent received command: %s' % command)
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
            else:
                raise AgentError('No such command: %s' % command_type)
            response['result'] = result
        except:
            logger.exception('Exception while processing command: %s', command)
            ex_type, ex, tb = sys.exc_info()
            response['exception'] = '%s: %s' % (ex_type.__name__, str(ex))
            response['traceback'] = traceback.format_tb(tb)
            del tb

        self._log.append((command, response))

        return response

    def _command_run(self, command):
        run = wandb_run.Run(mode='run',
                            sweep_id=self._sweep_id,
                            storage_id=command.get('run_storage_id'),
                            run_id=command.get('run_id'))

        # save the the wandb config to reflect the state of the run that the
        # the server generated.
        run.config.set_run_dir(run.dir)
        run.config.update({k: v['value'] for k, v in command['args'].items()})

        env = dict(os.environ)
        run.set_environment(env)

        flags = ["--{0}={1}".format(name, config['value'])
                 for name, config in command['args'].items()]

        agent_run_args = {
            'command': 'agent-run',
            'program': command['program'],
            'args': flags
        }
        internal_cli_path = os.path.join(
            os.path.dirname(__file__), 'internal_cli.py')
        self._run_processes[run.id] = subprocess.Popen(
            ['/usr/bin/env', 'python', internal_cli_path,
                json.dumps(agent_run_args)],
            env=env)

        # we track how many times the user has tried to stop this run
        # so we can escalate how hard we try to kill it in self._command_stop()
        self._run_processes[run.id].num_times_stopped = 0

    def _command_stop(self, command):
        run_id = command['run_id']
        logger.info('Stop: %s', run_id)
        if run_id in self._run_processes:
            proc = self._run_processes[run_id]
            try:
                if proc.num_times_stopped == 0:
                    proc.terminate()
                elif proc.num_times_stopped == 1:
                    proc.kill()
            except OSError:  # if process is already dead
                pass
            finally:
                proc.num_times_stopped += 1
        else:
            logger.error('Run %s not running', run_id)


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
