import json
import os

from wandb import util

METADATA_FNAME = 'wandb-metadata.json'


class Meta(object):
    """Used to store summary metrics during and after a run."""

    def __init__(self, out_dir='.'):
        self.fname = os.path.join(out_dir, METADATA_FNAME)
        try:
            self.data = json.load(open(self.fname))
        except (IOError, ValueError):
            self.data = {}

    def write(self):
        with open(self.fname, 'w') as f:
            s = util.json_dumps_safer(self.data, indent=4)
            f.write(s)
            f.write('\n')
