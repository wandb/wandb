from .history import History
from .summary import Summary

class Run(object):
    def __init__(self, dir, config):
        self.dir = dir
        self.config = config
        self.history = History(self.dir)
        self.summary = Summary(self.dir)