from .history import History
from .summary import Summary

class Run(object):
    def __init__(self, run_id, dir, config):
        self.id = run_id
        self.dir = dir
        self.config = config
        self.history = History(self.dir)
        self.summary = Summary(self.dir)