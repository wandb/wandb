from .scheduler import Scheduler


class TuneScheduler(Scheduler):
    """Scheduler that uses Ray's Tune to provide sweep suggestions.

    See: https://github.com/ray-project/ray/blob/master/python/ray/tune/suggest/_mock.py

    """

    # NOTE: This file will not be included with this PR,
    # I kept this here so that reviewers would better
    # understand the future context and resulting design choices

    pass
