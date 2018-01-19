import datetime
import os
import shortuuid

import wandb
from wandb import jsonlfile
from wandb import summary
from wandb import typedtable
from wandb import util

HISTORY_FNAME = 'wandb-history.jsonl'
EVENTS_FNAME = 'wandb-events.jsonl'
EXAMPLES_FNAME = 'wandb-examples.jsonl'


class Run(object):
    def __init__(self, run_id, dir, config):
        self.id = run_id
        self._dir = os.path.abspath(dir)
        self.config = config
        self._made_dir = False

        # Use internal self._dir so dir isn't created yet (it should only
        # be created when the user accesses a run member for the first time).
        self._history = None
        self._events = None
        self._summary = None
        self._examples = None

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
    def has_summary(self):
        return self._summary is not None

    @property
    def history(self):
        self._mkdir()
        if self._history is None:
            self._history = jsonlfile.JsonlFile(HISTORY_FNAME, self._dir)
        return self._history

    @property
    def events(self):
        self._mkdir()
        if self._events is None:
            self._events = jsonlfile.JsonlEventsFile(EVENTS_FNAME, self._dir)
        return self._events

    @property
    def has_history(self):
        return self._history is not None

    @property
    def examples(self):
        self._mkdir()
        if self._examples is None:
            self._examples = typedtable.TypedTable(
                jsonlfile.JsonlFile(EXAMPLES_FNAME, self._dir))
        return self._examples

    @property
    def has_examples(self):
        return self._examples is not None


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
