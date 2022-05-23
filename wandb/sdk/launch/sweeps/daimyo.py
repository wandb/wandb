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

    def __iter__(self):
        #returning __iter__ object
        return self

    def __next__(self):
        #comparing present_day with end_date,
        #if present_day greater then end_date stoping the iteration
        if self._present_day >= self.end_date:
            raise StopIteration
        today = self._present_day
        self._present_day += timedelta(days=1)
        return today

