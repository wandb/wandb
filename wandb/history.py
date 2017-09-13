import csv
import os

from wandb import util

HISTORY_FNAME = 'wandb-history.json'

class History(object):
    """Used to store data that changes over time during runs. """
    def __init__(self, out_dir='.'):
        self.out_fname = os.path.join(out_dir, HISTORY_FNAME)
        self.rows = []

    def _write(self):
        with open(self.out_fname, 'w') as f:
            s = util.json_dumps_safer(self.rows, indent=4)
            f.write(s)
            f.write('\n')
    
    def add(self, row):
        self.rows.append(row)
        self._write()