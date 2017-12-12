import socket
from wandb.api import Api
from wandb import util
from wandb import runner
import multiprocessing


class Agent(object):
    POLL_INTERVAL = 5

    def __init__(self, api, queue, wandb_runner):
        self._api = api
        self._queue = queue
        self._runner = wandb_runner

    def run(self):
        agent = self._api.register_agent(socket.gethostname(), True)
        agent_id = agent['id']
        while True:
            commands = util.read_many_from_queue(
                    self._queue, 100, self.POLL_INTERVAL)
            commands += self._api.agent_heartbeat(agent_id, {}, {})
            for command in commands:
                self._process_command(command)
    
    def _process_command(self, command):
        print('Agent received command: %s' % command)
        command_type = command['type']
        if command['type'] == 'run':
            self._command_run(command)
        elif command['type'] == 'stop':
            self._command_stop(command)

    def _command_run(self, command):
        self._runner.run(command['program'], command['config'])

    def _command_stop(self, command):
        self._runner.stop(command['run_id'])

class AgentApi(object):
    def __init__(self, queue):
        self._queue = queue

    def command(self, command):
        self._queue.put(command)


def run_agent():
    api = Api()
    wandb_runner = runner.Runner(api)
    queue = multiprocessing.Queue()
    agent = Agent(api, queue, wandb_runner)
    p = multiprocessing.Process(target=agent.run)
    p.start()
    return AgentApi(queue)
