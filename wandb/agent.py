import logging
import multiprocessing
import os
import socket
import sys
import traceback

import six

import wandb
from wandb.api import Api
from wandb.config import Config
from wandb import util
from wandb import sync
from wandb import wandb_run


logger = logging.getLogger(__name__)


class AgentError(Exception):
    pass


class Agent(object):
    POLL_INTERVAL = 5

    def __init__(self, api, queue, sweep_id=None):
        self._api = api
        self._queue = queue
        self._run_managers = {}  # keyed by run.id (GQL run name)
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
                commands = util.read_many_from_queue(self._queue, 100, self.POLL_INTERVAL)
                for command in commands:
                    command['resp_queue'].put(self._process_command(command))

                logger.info('Running runs: %s', self._run_managers.keys())
                run_status = {}
                for run_id, run_manager in six.iteritems(self._run_managers):
                    if run_manager.poll() is None:
                        run_status[run_id] = True

                commands = self._api.agent_heartbeat(agent_id, {}, run_status)

                # TODO: send _server_responses
                self._server_responses = []
                for command in commands:
                    self._server_responses.append(self._process_command(command))
        except KeyboardInterrupt:
            pass
        finally:
            try:
                # TODO(adrian): hitting ctrl-c a lot sometimes causes the following:
                """
                  File "/Users/adrian/src/wandb-client/wandb/agent.py", line 66, in run
                    run_manager.proc.terminate()
                  File "/Users/adrian/.pyenv/versions/2.7.12/lib/python2.7/subprocess.py", line 1567, in terminate
                    self.send_signal(signal.SIGTERM)
                  File "/Users/adrian/.pyenv/versions/2.7.12/lib/python2.7/subprocess.py", line 1562, in send_signal
                    os.kill(self.pid, sig)
                OSError: [Errno 3] No such process
                """
                wandb.termlog('Terminating and syncing runs. Press ctrl-c to kill.')
                for run_id, run_manager in six.iteritems(self._run_managers):
                    run_manager.proc.terminate()
                for run_id, run_manager in six.iteritems(self._run_managers):
                    run_manager.proc.wait()
                    run_manager.poll()  # clean up if necessary
            except KeyboardInterrupt:
                wandb.termlog('Killing and syncing runs. Press ctrl-c again to quit.')
                for run_id, run_manager in six.iteritems(self._run_managers):
                    run_manager.proc.kill()
                for run_id, run_manager in six.iteritems(self._run_managers):
                    run_manager.clean_up(False)

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
        config = Config.from_environment_or_defaults()
        run = wandb_run.Run(mode='run', config=config, sweep_id=self._sweep_id)

        api = Api()
        api.set_current_run_id(run.id)

        root = api.git.root
        remote_url = api.git.remote_url
        host = socket.gethostname()
        # handle non-git directories
        if not root:
            root = os.path.abspath(os.getcwd())
            remote_url = 'file://%s%s' % (host, root)

        program = command['program']
        args = command['args']

        upsert_result = api.upsert_run(name=run.id,
            project=api.settings("project"),
            entity=api.settings("entity"),
            config=run.config.as_dict(), description=run.description, host=host,
            program_path=program, repo=remote_url, sweep_name=run.sweep_id)
        run.storage_id = upsert_result['id']
        env = dict(os.environ)
        run.set_environment(env)
        # TODO(adrian): we need to do the following if we use pipes instead of PTYs (eg. for windows)
        # tell child python interpreters we accept utf-8
        # env['PYTHONIOENCODING'] = 'UTF-8'

        # TODO(adrian): do this in a separate process so we can be sure sync threads etc
        # get cleaned up properly?
        self._run_managers[run.id] = sync.Sync(api, run, program, args, env)

    def _command_stop(self, command):
        run_id = command['run_id']
        logger.info('Stop: %s', run_id)
        if run_id in self._run_managers:
            self._run_managers[run_id].proc.kill()
            self._run_managers[run_id].clean_up(False)
            del self._run_managers[run_id]
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
    api = Api()
    queue = multiprocessing.Queue()
    agent = Agent(api, queue, sweep_id=sweep_id)
    agent.run()
