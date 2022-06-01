from .scheduler import Scheduler


class TuneScheduler(Scheduler):
    """Scheduler that uses Ray's Tune to provide sweep suggestions.

    See: https://github.com/ray-project/ray/blob/master/python/ray/tune/suggest/_mock.py

    """

    pass
