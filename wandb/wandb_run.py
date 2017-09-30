import datetime
import os
import shortuuid

import wandb
from wandb import history
from wandb import summary
from wandb import util


class Run(object):
    def __init__(self, run_id, dir, config):
        self.id = run_id
        self._dir = os.path.abspath(dir)
        self.config = config
        self._made_dir = False

        # Use internal self._dir so dir isn't created yet (it should only
        # be created when the user accesses a run member for the first time).
        self._history = None
        self._summary = None

    def _mkdir(self):
        if self._made_dir:
            return
        util.mkdir_exists_ok(self._dir)

    @property
    def dir(self):
        self._mkdir()
        return self._dir

    @property
    def summary(self):
        self._mkdir()
        if self._summary is None:
            self._summary = summary.Summary(self._dir)
        return self._summary

    @property
    def history(self):
        self._mkdir()
        if self._history is None:
            self._history = history.History(self._dir)
        return self._history


def generate_id():
    # ~3t run ids (36**8)
    run_gen = shortuuid.ShortUUID(alphabet=list(
        "0123456789abcdefghijklmnopqrstuvwxyz"))
    return run_gen.random(8)


def run_dir_path(run_id, dry=False):
    if dry:
        prefix = 'dryrun'
    else:
        prefix = 'run'
    time_str = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    return os.path.join(wandb.wandb_dir(), '%s-%s-%s' % (prefix, time_str, run_id))
