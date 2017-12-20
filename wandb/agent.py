import multiprocessing
import socket
import sys
import traceback
from wandb.api import Api
from wandb import util
from wandb import runner


class AgentError(Exception):
    pass


class Agent(object):
    POLL_INTERVAL = 5

    def __init__(self, api, queue, wandb_runner, sweep_id=None):
        self._api = api
        self._queue = queue
        self._runner = wandb_runner
        self._server_responses = []
        self._sweep_id = sweep_id
        self._log = []

    def run(self):
        # TODO: include sweep ID
        agent = self._api.register_agent(
            socket.gethostname(), True, sweep_id=self._sweep_id)
        agent_id = agent['id']
        while True:
            commands = util.read_many_from_queue(
                self._queue, 100, self.POLL_INTERVAL)
            # TODO: send _server_responses
            running_runs = self._runner.running_runs()
            print('Running runs: ', running_runs)
            run_status = {}
            for run in running_runs:
                run_status[run] = True
            heartbeat_commands = self._api.agent_heartbeat(
                agent_id, {}, run_status)
            self._server_responses = []
            for command in heartbeat_commands:
                command['origin'] = 'server'
            commands += heartbeat_commands
            for command in commands:
                response = self._process_command(command)
                if command['origin'] == 'server':
                    self._server_responses.append(response)
                elif command['origin'] == 'local':
                    command['resp_queue'].put(response)

    def _process_command(self, command):
        print('Agent received command: %s' % command)
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
            ex_type, ex, tb = sys.exc_info()
            response['exception'] = '%s: %s' % (ex_type.__name__, str(ex))
            response['traceback'] = traceback.format_tb(tb)
            del tb

        self._log.append((command, response))

        return response

    def _command_run(self, command):
        return self._runner.run(command['program'], command['args'],
                                sweep_id=self._sweep_id)

    def _command_stop(self, command):
        return self._runner.stop(command['run_id'])


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
    wandb_runner = runner.Runner(api)
    queue = multiprocessing.Queue()
    agent = Agent(api, queue, wandb_runner, sweep_id=sweep_id)
    p = multiprocessing.Process(target=agent.run)
    p.start()
    return AgentApi(queue)
