import json
import os

import wandb
from wandb import util
from wandb.meta import Meta
import six

SUMMARY_FNAME = 'wandb-summary.json'


class Summary(object):
    """Used to store summary metrics during and after a run."""

    def __init__(self, out_dir='.'):
        self._fname = os.path.join(out_dir, SUMMARY_FNAME)
        self.load()

    def load(self):
        try:
            self._summary = json.load(open(self._fname))
        except (IOError, ValueError):
            self._summary = {}

    def _write(self):
        with open(self._fname, 'w') as f:
            s = util.json_dumps_safer(self._summary, indent=4)
            f.write(s)
            f.write('\n')

    def _transform(self, v):
        if isinstance(v, wandb.Histogram):
            return wandb.Histogram.transform(v)
        else:
            return v

    def __getitem__(self, k):
        return self._summary[k]

    def __setitem__(self, k, v):
        self._summary[k] = self._transform(v)
        self._write()

    def __setattr__(self, k, v):
        if k.startswith("_"):
            super(Summary, self).__setattr__(k, v)
        else:
            self._summary[k] = self._transform(v)
            self._write()

    def __getattr__(self, k):
        if k.startswith("_"):
            super(Summary, self).__getattr__(k)
        else:
            return self._summary[k]

    def __delitem__(self, k):
        del self._summary[k]
        self._write()

    def __repr__(self):
        return json.dumps(self._summary, indent=4)

    def get(self, k, default=None):
        return self._summary.get(k, default)

    def update(self, key_vals):
        if not isinstance(key_vals, dict):
            raise wandb.Error('summary.update expects dict')
        summary = {}
        for k, v in six.iteritems(key_vals):
            if isinstance(v, dict) and v.get("_type") == "image":
                continue
            summary[k] = self._transform(v)
        self._summary.update(summary)
        self._write()
