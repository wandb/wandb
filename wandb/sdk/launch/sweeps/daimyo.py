from abc import ABC
import logging
from typing import Any, Dict

from wandb.wandb_agent import Agent as WandbSweepAgent

_logger = logging.getLogger(__name__)


class Daimyo(ABC):
    """ Daimyo is a Lord in feudal Japan :japanese_castle: and Boba Fett's title in the Mandalorian.

    In this context, the Daimyo is a controller/agent that will populate a Launch Queue with
    jobs to run for a sweep.
    """

    def __init__():
        pass

    def start():
        pass

    def kill():
        pass

    def stop():
        pass

def launch_daimyo(sweep_id, queue, entity=None, project=None):
    pass
