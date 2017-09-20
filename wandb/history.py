import csv
import os

from wandb import util

HISTORY_FNAME = 'wandb-history.jsonl'

class History(object):
    """Used to store data that changes over time during runs. """
    def __init__(self, out_dir='.'):
        self.fname = os.path.join(out_dir, HISTORY_FNAME)
        self._file = open(self.fname, 'w')
        self.rows = []

    def add(self, row):
        self.rows.append(row)
        self._file.write(util.json_dumps_safer(row))
        self._file.write('\n')
        self._file.flush()