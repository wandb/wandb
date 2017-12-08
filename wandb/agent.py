import time
import logging
from wandb import wandb_dir
from wandb.pusher import AgentPuller


class Agent(object):
    def __init__(self, entity=None):
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)
        self.logger.addHandler(logging.FileHandler("agent.log", "w"))
        self.puller = AgentPuller(self, entity=entity, logger=self.logger)

    def run(self):
        self.logger.info('WandB Agent Starting')
        self.puller.run()

    def handle_event(self, event):
        pass
