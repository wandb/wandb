import json
import os

import wandb
from wandb import util
from wandb.meta import Meta

SUMMARY_FNAME = 'wandb-summary.json'


class Summary(object):
    """Used to store summary metrics during and after a run."""

    def __init__(self, out_dir='.'):
        self.fname = os.path.join(out_dir, SUMMARY_FNAME)
        self.load()

    def load(self):
        try:
            self.summary = json.load(open(self.fname))
        except IOError:
            self.summary = {}

    def _write(self):
        with open(self.fname, 'w') as f:
            s = util.json_dumps_safer(self.summary, indent=4)
            f.write(s)
            f.write('\n')

    def __getitem__(self, k):
        return self.summary[k]

    def __setitem__(self, k, v):
        self.summary[k] = v
        self._write()

    def __delitem__(self, k):
        del self.summary[k]
        self._write()

    def get(self, k, default=None):
        return self.summary.get(k, default)

    def update(self, key_vals):
        if not isinstance(key_vals, dict):
            raise wandb.Error('summary.update expects dict')
        self.summary.update(key_vals)
        self._write()
