import datetime
import logging
import os
import shortuuid
import socket
import json
import yaml
from sentry_sdk import configure_scope

import wandb
from wandb import history
from wandb import jsonlfile
from wandb import summary
from wandb import meta
from wandb import typedtable
from wandb import util
from wandb.file_pusher import FilePusher
from wandb.apis import InternalApi
from wandb.wandb_config import Config
import six
from six.moves import configparser
import atexit
import sys
from watchdog.utils.dirsnapshot import DirectorySnapshot

HISTORY_FNAME = 'wandb-history.jsonl'
EVENTS_FNAME = 'wandb-events.jsonl'
CONFIG_FNAME = 'config.yaml'
USER_CONFIG_FNAME = 'config.json'
SUMMARY_FNAME = 'wandb-summary.json'
METADATA_FNAME = 'wandb-metadata.json'
EXAMPLES_FNAME = 'wandb-examples.jsonl'
DESCRIPTION_FNAME = 'description.md'


class Run(object):
    def __init__(self, run_id=None, mode=None, dir=None, group=None, job_type=None, config=None, sweep_id=None, storage_id=None, description=None, resume=None, program=None, wandb_dir=None):
        # self.id is actually stored in the "name" attribute in GQL
        self.id = run_id if run_id else generate_id()
        self.resume = resume if resume else 'never'
        self.mode = mode if mode else 'run'
        self.group = group
        self.job_type = job_type
        self.pid = os.getpid()

        self.program = program
        if not self.program:
            try:
                import __main__
                self.program = __main__.__file__
            except (ImportError, AttributeError):
                # probably `python -c`, an embedded interpreter or something
                self.program = '<python with no main file>'
        self.wandb_dir = wandb_dir

        with configure_scope() as scope:
            api = InternalApi()
            scope.set_tag("project", api.settings("project"))
            scope.set_tag("entity", api.settings("entity"))
            scope.set_tag("url", self.get_url(api))

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
        self._jupyter_agent = None
        self._examples = None

    def _init_jupyter_agent(self):
        from wandb.jupyter import JupyterAgent
        self._jupyter_agent = JupyterAgent()

    def _stop_jupyter_agent(self):
        self._jupyter_agent.stop()

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
        resume = environment.get('WANDB_RESUME')
        storage_id = environment.get('WANDB_RUN_STORAGE_ID')
        mode = environment.get('WANDB_MODE')
        disabled = InternalApi().disabled()
        if not mode and disabled:
            mode = "dryrun"
        elif disabled and mode != "dryrun":
            wandb.termlog(
                "WARNING: WANDB_MODE is set to run, but W&B was disabled.  Run `wandb on` to remove this message")
        elif disabled:
            wandb.termlog(
                'W&B is disabled in this directory.  Run `wandb on` to enable cloud syncing.')

        group = environment.get('WANDB_RUN_GROUP')
        job_type = environment.get('WANDB_JOB_TYPE')
        run_dir = environment.get('WANDB_RUN_DIR')
        sweep_id = environment.get('WANDB_SWEEP_ID')
        program = environment.get('WANDB_PROGRAM')
        wandb_dir = environment.get('WANDB_DIR')
        config = Config.from_environment_or_defaults()
        run = cls(run_id, mode, run_dir,
                  group, job_type, config,
                  sweep_id, storage_id, program=program,
                  wandb_dir=wandb_dir,
                  resume=resume)
        return run

    @classmethod
    def from_directory(cls, directory, project=None, entity=None, run_id=None, api=None):
        api = api or InternalApi()
        run_id = run_id or generate_id()
        run = Run(run_id=run_id, dir=directory)
        project = project or api.settings(
            "project") or run.auto_project_name(api=api)
        if project is None:
            raise ValueError("You must specify project")
        api.set_current_run_id(run_id)
        api.set_setting("project", project)
        if entity:
            api.set_setting("entity", entity)
        res = api.upsert_run(name=run_id, project=project, entity=entity)
        entity = res["project"]["entity"]["name"]
        wandb.termlog("Syncing {} to:".format(directory))
        wandb.termlog(run.get_url(api))

        file_api = api.get_file_stream_api()
        snap = DirectorySnapshot(directory)
        paths = [os.path.relpath(abs_path, directory)
                 for abs_path in snap.paths if os.path.isfile(abs_path)]
        run_update = {"id": res["id"]}
        tfevents = sorted([p for p in snap.paths if ".tfevents." in p])
        history = next((p for p in snap.paths if HISTORY_FNAME in p), None)
        event = next((p for p in snap.paths if EVENTS_FNAME in p), None)
        config = next((p for p in snap.paths if CONFIG_FNAME in p), None)
        user_config = next(
            (p for p in snap.paths if USER_CONFIG_FNAME in p), None)
        summary = next((p for p in snap.paths if SUMMARY_FNAME in p), None)
        meta = next((p for p in snap.paths if METADATA_FNAME in p), None)
        if history:
            wandb.termlog("Uploading history metrics")
            file_api.stream_file(history)
            snap.paths.remove(history)
        elif len(tfevents) > 0:
            from wandb import tensorflow as wbtf
            wandb.termlog("Found tfevents file, converting.")
            for file in tfevents:
                summary = wbtf.stream_tfevents(file, file_api)
        else:
            wandb.termerror(
                "No history or tfevents files found, only syncing files")
        if event:
            file_api.stream_file(event)
            snap.paths.remove(event)
        if config:
            run_update["config"] = yaml.load(open(config))
        elif user_config:
            # TODO: half backed support for config.json
            run_update["config"] = {k: {"value": v}
                                    for k, v in six.iteritems(user_config)}
        if summary:
            run_update["summary_metrics"] = open(summary).read()
        if meta:
            meta = json.load(open(meta))
            run_update["commit"] = meta["git"].get("commit")
            run_update["repo"] = meta["git"].get("remote")
            run_update["host"] = meta["host"]
            run_update["program_path"] = meta["program"]
            run_update["job_type"] = meta["jobType"]
        else:
            run_update["host"] = socket.gethostname()

        wandb.termlog("Updating run and uploading files")
        api.upsert_run(**run_update)
        pusher = FilePusher(api)
        for k in paths:
            path = os.path.abspath(os.path.join(directory, k))
            pusher.update_file(k, path)
            pusher.file_changed(k, path)
        pusher.finish()
        pusher.print_status()
        wandb.termlog("Finished!")
        return run

    def auto_project_name(self, api):
        # if we're in git, set project name to git repo name + relative path within repo
        root_dir = api.git.root_dir
        if root_dir is None:
            return None
        repo_name = os.path.basename(root_dir)
        program = self.program
        if program is None:
            return repo_name
        if not os.path.isabs(program):
            program = os.path.join(os.curdir, program)
        prog_dir = os.path.dirname(os.path.abspath(program))
        if not prog_dir.startswith(root_dir):
            return repo_name
        project = repo_name
        sub_path = os.path.relpath(prog_dir, root_dir)
        if sub_path != '.':
            project += '-' + sub_path
        return project.replace(os.sep, '_')

    def save(self, id=None, program=None, summary_metrics=None, num_retries=None, api=None):
        api = api or InternalApi()
        project = api.settings('project')
        if project is None:
            project = self.auto_project_name(api)
        upsert_result = api.upsert_run(id=id or self.storage_id, name=self.id, commit=api.git.last_commit,
                                       project=project, entity=api.settings(
                                           "entity"),
                                       group=self.group,
                                       config=self.config.as_dict(), description=self.description, host=socket.gethostname(),
                                       program_path=program or self.program, repo=api.git.remote_url, sweep_name=self.sweep_id,
                                       summary_metrics=summary_metrics, job_type=self.job_type, num_retries=num_retries)
        self.storage_id = upsert_result['id']
        return upsert_result

    def set_environment(self, environment=None):
        """Set environment variables needed to reconstruct this object inside
        a user scripts (eg. in `wandb.init()`).
        """
        if environment is None:
            environment = os.environ
        environment['WANDB_RUN_ID'] = self.id
        environment['WANDB_RESUME'] = self.resume
        if self.storage_id:
            environment['WANDB_RUN_STORAGE_ID'] = self.storage_id
        environment['WANDB_MODE'] = self.mode
        environment['WANDB_RUN_DIR'] = self.dir

        if self.group:
            environment['WANDB_RUN_GROUP'] = self.group
        if self.job_type:
            environment['WANDB_JOB_TYPE'] = self.job_type
        if self.wandb_dir:
            environment['WANDB_DIR'] = self.wandb_dir
        if self.sweep_id is not None:
            environment['WANDB_SWEEP_ID'] = self.sweep_id
        if self.program is not None:
            environment['WANDB_PROGRAM'] = self.program

    def _mkdir(self):
        util.mkdir_exists_ok(self._dir)

    def get_url(self, api=None):
        api = api or InternalApi()
        return "{base}/{entity}/{project}/runs/{run}".format(
            base=api.app_url,
            entity=api.settings('entity'),
            project=api.settings('project'),
            run=self.id
        )

    def __repr__(self):
        return "W&B Run %s" % self.get_url()

    @property
    def host(self):
        return socket.gethostname()

    @property
    def dir(self):
        return self._dir

    @property
    def log_fname(self):
        return os.path.join(self.dir, 'wandb-debug.log')

    def enable_logging(self):
        """Enable Python logging to a file in this Run's directory.

        Currently no way to disable logging after it's enabled.
        """
        handler = logging.FileHandler(self.log_fname)
        handler.setLevel(logging.INFO)

        formatter = logging.Formatter(
            '%(asctime)s %(levelname)-7s %(threadName)-10s:%(process)d [%(filename)s:%(funcName)s():%(lineno)s] %(message)s')
        handler.setFormatter(formatter)

        root = logging.getLogger()
        root.addHandler(handler)

    @property
    def summary(self):
        if self._summary is None:
            self._summary = summary.FileSummary(self._dir)
        return self._summary

    @property
    def has_summary(self):
        return self._summary or os.path.exists(os.path.join(self._dir, summary.SUMMARY_FNAME))

    def _history_added(self, row):
        if self._summary is None:
            self._summary = summary.FileSummary(self._dir)
        if self._jupyter_agent:
            self._jupyter_agent.start()
        self._summary.update(row, overwrite=False)

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
            self._events = None
        if self._history is not None:
            self._history.close()
            self._history = None


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
