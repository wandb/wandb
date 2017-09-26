import csv
import os

import wandb
from wandb import util

HISTORY_FNAME = 'wandb-history.jsonl'


class History(object):
    """Used to store data that changes over time during runs. """

    def __init__(self, out_dir='.'):
        self.fname = os.path.join(out_dir, HISTORY_FNAME)
        self._file = open(self.fname, 'w')
        self.rows = []

    def keys(self):
        if self.rows:
            return self.rows[0].keys()
        return []

    def column(self, key):
        return [r[key] for r in self.rows]

    def add(self, row):
        if not isinstance(row, dict):
            raise wandb.Error('history.add expects dict')
        self.rows.append(row)
        self._file.write(util.json_dumps_safer(row))
        self._file.write('\n')
        self._file.flush()
