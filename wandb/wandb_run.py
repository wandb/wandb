import datetime
import os
import shortuuid

import wandb
from wandb import history
from wandb import jsonlfile
from wandb import summary
from wandb import meta
from wandb import typedtable
from wandb import util
from wandb.config import Config
import atexit
import sys

HISTORY_FNAME = 'wandb-history.jsonl'
EVENTS_FNAME = 'wandb-events.jsonl'
EXAMPLES_FNAME = 'wandb-examples.jsonl'
DESCRIPTION_FNAME = 'description.md'


class Run(object):
    def __init__(self, run_id=None, mode=None, dir=None, config=None, sweep_id=None, storage_id=None, description=None):
        # self.id is actually stored in the "name" attribute in GQL
        self.id = run_id if run_id else generate_id()
        self.mode = mode if mode else 'dryrun'

        if dir is None:
            self._dir = run_dir_path(self.id, dry=self.mode == 'dryrun')
        else:
            self._dir = os.path.abspath(dir)
        self._mkdir()

        if config is None:
            self.config = Config()
        else:
            self.config = config

        # this is the GQL ID:
        self.storage_id = storage_id
        # socket server, currently only available in headless mode
        self.socket = None

        if description is not None:
            self.description = description
        # An empty description.md may have been created by RunManager() so it's
        # important that we overwrite empty strings here.
        if not self.description:
            self.description = self.id

        self.sweep_id = sweep_id

        self._history = None
        self._events = None
        self._summary = None
        self._meta = None
        self._user_accessed_summary = False
        self._examples = None

    @classmethod
    def from_environment_or_defaults(cls, environment=None):
        """Create a Run object taking values from the local environment where possible.

        The run ID comes from WANDB_RUN_ID or is randomly generated.
        The run mode ("dryrun", or "run") comes from WANDB_MODE or defaults to "dryrun".
        The run directory comes from WANDB_RUN_DIR or is generated from the run ID.

        The Run will have a .config attribute but its run directory won't be set by
        default.
        """
        if environment is None:
            environment = os.environ
        run_id = environment.get('WANDB_RUN_ID')
        storage_id = environment.get('WANDB_RUN_STORAGE_ID')
        mode = environment.get('WANDB_MODE')
        run_dir = environment.get('WANDB_RUN_DIR')
        sweep_id = environment.get('WANDB_SWEEP_ID')
        config = Config.from_environment_or_defaults()
        run = cls(run_id, mode, run_dir, config, sweep_id, storage_id)
        return run

    def set_environment(self, environment=None):
        """Set environment variables needed to reconstruct this object inside
        a user scripts (eg. in `wandb.init()`).
        """
        if environment is None:
            environment = os.environ
        environment['WANDB_RUN_ID'] = self.id
        if self.storage_id:
            environment['WANDB_RUN_STORAGE_ID'] = self.storage_id
        environment['WANDB_MODE'] = self.mode
        environment['WANDB_RUN_DIR'] = self.dir
        if self.sweep_id is not None:
            environment['WANDB_SWEEP_ID'] = self.sweep_id

    def _mkdir(self):
        util.mkdir_exists_ok(self._dir)

    def get_url(self, api):
        return "{base}/{entity}/{project}/runs/{run}".format(
            base=api.app_url,
            entity=api.settings('entity'),
            project=api.settings('project'),
            run=self.id
        )

    @property
    def dir(self):
        return self._dir

    @property
    def summary(self):
        # We use this to track whether user has accessed summary
        self._user_accessed_summary = True
        if self._summary is None:
            self._summary = summary.Summary(self._dir)
        return self._summary

    @property
    def has_summary(self):
        return self._summary or os.path.exists(os.path.join(self._dir, summary.SUMMARY_FNAME))

    def _history_added(self, row):
        if self._summary is None:
            self._summary = summary.Summary(self._dir)
        if not self._user_accessed_summary:
            self._summary.update(row)

    @property
    def history(self):
        if self._history is None:
            self._history = history.History(
                HISTORY_FNAME, self._dir, add_callback=self._history_added)
        return self._history

    @property
    def has_history(self):
        return self._history or os.path.exists(os.path.join(self._dir, HISTORY_FNAME))

    @property
    def events(self):
        if self._events is None:
            self._events = jsonlfile.JsonlEventsFile(EVENTS_FNAME, self._dir)
        return self._events

    @property
    def has_events(self):
        return self._events or os.path.exists(os.path.join(self._dir, EVENTS_FNAME))

    @property
    def examples(self):
        if self._examples is None:
            self._examples = typedtable.TypedTable(
                jsonlfile.JsonlFile(EXAMPLES_FNAME, self._dir))
        return self._examples

    @property
    def has_examples(self):
        return self._examples or os.path.exists(os.path.join(self._dir, EXAMPLES_FNAME))

    @property
    def description_path(self):
        return os.path.join(self.dir, DESCRIPTION_FNAME)

    @property
    def description(self):
        try:
            with open(self.description_path) as d_file:
                return d_file.read()
        except IOError:
            # TODO(adrian): should probably check specifically for a nonexistant file error
            return None

    @description.setter
    def description(self, description):
        with open(self.description_path, 'w') as d_file:
            d_file.write(description)
        return description

    def close_files(self):
        """Close open files to avoid Python warnings on termination:

        Exception ignored in: <_io.FileIO name='wandb/dryrun-20180130_144602-9vmqjhgy/wandb-history.jsonl' mode='wb' closefd=True>
        ResourceWarning: unclosed file <_io.TextIOWrapper name='wandb/dryrun-20180130_144602-9vmqjhgy/wandb-history.jsonl' mode='w' encoding='UTF-8'>
        """
        if self._events is not None:
            self._events.close()
        if self._history is not None:
            self._history.close()


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
    time_str = datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    return os.path.join(wandb.wandb_dir(), '%s-%s-%s' % (prefix, time_str, run_id))
