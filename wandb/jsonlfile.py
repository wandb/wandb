import collections
import json
import os
import time
from threading import Lock

import wandb
from wandb import util


class JsonlEventsFile(object):
    """Used to store events during a run. """

    def __init__(self, fname, out_dir='.'):
        self._start_time = wandb.START_TIME
        self.fname = os.path.join(out_dir, fname)
        self._file = open(self.fname, 'w')
        self.buffer = []
        self.lock = Lock()

    def flatten(self, dictionary):
        if type(dictionary) == dict:
            for k, v in list(dictionary.items()):
                if type(v) == dict:
                    self.flatten(v)
                    dictionary.pop(k)
                    for k2, v2 in v.items():
                        dictionary[k + "." + k2] = v2

    def track(self, event, properties, timestamp=None, _wandb=False):
        if not isinstance(properties, collections.Mapping):
            raise wandb.Error('event.track expects dict-like object')
        self.lock.acquire()
        try:
            row = {}
            row[event] = properties
            self.flatten(row)
            if _wandb:
                row["_wandb"] = _wandb
            row["_timestamp"] = int(timestamp or time.time())
            row['_runtime'] = int(time.time() - self._start_time)
            self._file.write(util.json_dumps_safer(row))
            self._file.write('\n')
            self._file.flush()
        finally:
            self.lock.release()

    def close(self):
        self.lock.acquire()
        try:
            self._file.close()
            self._file = None
        finally:
            self.lock.release()
