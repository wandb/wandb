import datetime
import logging
import os
import socket
import json
import yaml
import fnmatch
import tempfile
import shutil
import glob

from sentry_sdk import configure_scope

from . import env
import wandb
from wandb import history
from wandb import jsonlfile
from wandb import summary
from wandb import meta
from wandb import typedtable
from wandb import util
from wandb.core import termlog
from wandb import data_types
from wandb.file_pusher import FilePusher
from wandb.apis import InternalApi, CommError
from wandb.wandb_config import Config
import six
from six.moves import input
from six.moves import urllib
import atexit
import sys
from watchdog.utils.dirsnapshot import DirectorySnapshot

RESUME_FNAME = 'wandb-resume.json'
HISTORY_FNAME = 'wandb-history.jsonl'
EVENTS_FNAME = 'wandb-events.jsonl'
CONFIG_FNAME = 'config.yaml'
USER_CONFIG_FNAME = 'config.json'
SUMMARY_FNAME = 'wandb-summary.json'
METADATA_FNAME = 'wandb-metadata.json'
DESCRIPTION_FNAME = 'description.md'


class Run(object):
    def __init__(self, run_id=None, mode=None, dir=None, group=None, job_type=None,
                 config=None, sweep_id=None, storage_id=None, description=None, resume=None,
                 program=None, args=None, wandb_dir=None, tags=None, name=None, notes=None,
                 api=None):
        """Create a Run.

        Arguments:
            description (str): This is the old, deprecated style of description: the run's
                name followed by a newline, followed by multiline notes.
        """
        # self.storage_id is "id" in GQL.
        self.storage_id = storage_id
        # self.id is "name" in GQL.
        self.id = run_id if run_id else util.generate_id()
        # self._name is  "display_name" in GQL.
        self._name = None
        self.notes = None

        self.resume = resume if resume else 'never'
        self.mode = mode if mode else 'run'
        self.group = group
        self.job_type = job_type
        self.pid = os.getpid()
        self.resumed = False  # we set resume when history is first accessed
        if api:
            if api.current_run_id and api.current_run_id != self.id:
                raise RuntimeError('Api object passed to run {} is already being used by run {}'.format(
                    self.id, api.current_run_id))
            else:
                api.set_current_run_id(self.id)
        self._api = api

        if dir is None:
            self._dir = run_dir_path(self.id, dry=self.mode == 'dryrun')
        else:
            self._dir = os.path.abspath(dir)
        self._mkdir()

        # self.name and self.notes used to be combined into a single field.
        # Now if name and notes don't have their own values, we get them from
        # self._name_and_description, but we don't update description.md
        # if they're changed. This is to discourage relying on self.description
        # and self._name_and_description so that we can drop them later.
        #
        # This needs to be set before name and notes because name and notes may
        # influence it. They have higher precedence.
        self._name_and_description = None
        if description:
            wandb.termwarn('Run.description is deprecated. Please use wandb.init(notes="long notes") instead.')
            self._name_and_description = description
        elif os.path.exists(self.description_path):
            with open(self.description_path) as d_file:
                self._name_and_description = d_file.read()

        if name is not None:
            self.name = name
        if notes is not None:
            self.notes = notes

        self.program = program
        if not self.program:
            try:
                import __main__
                self.program = __main__.__file__
            except (ImportError, AttributeError):
                # probably `python -c`, an embedded interpreter or something
                self.program = '<python with no main file>'
        self.args = args
        if self.args is None:
            self.args = sys.argv[1:]
        self.wandb_dir = wandb_dir

        with configure_scope() as scope:
            self.project = self.api.settings("project")
            scope.set_tag("project", self.project)
            scope.set_tag("entity", self.entity)
            try:
                scope.set_tag("url", self.get_url(self.api, network=False))  # TODO: Move this somewhere outside of init
            except CommError:
                pass

        if self.resume == "auto":
            util.mkdir_exists_ok(wandb.wandb_dir())
            resume_path = os.path.join(wandb.wandb_dir(), RESUME_FNAME)
            with open(resume_path, "w") as f:
                f.write(json.dumps({"run_id": self.id}))

        if config is None:
            self.config = Config()
        else:
            self.config = config

        # socket server, currently only available in headless mode
        self.socket = None

        self.tags = tags if tags else []

        self.sweep_id = sweep_id

        self._history = None
        self._events = None
        self._summary = None
        self._meta = None
        self._run_manager = None
        self._jupyter_agent = None

    @property
    def api(self):
        if self._api is None:
            self._api = InternalApi()
            self._api.set_current_run_id(self.id)
        return self._api

    @property
    def entity(self):
        return self.api.settings('entity')

    @entity.setter
    def entity(self, entity):
        self.api.set_setting("entity", entity)

    @property
    def path(self):
        # TODO: theres an edge case where self.entity is None
        return "/".join([str(self.entity), self.project_name(), self.id])

    def _init_jupyter_agent(self):
        from wandb.jupyter import JupyterAgent
        self._jupyter_agent = JupyterAgent()

    def _stop_jupyter_agent(self):
        self._jupyter_agent.stop()

    def send_message(self, options):
        """ Sends a message to the wandb process changing the policy
        of saved files.  This is primarily used internally by wandb.save
        """
        if not options.get("save_policy") and not options.get("tensorboard"):
            raise ValueError(
                "Only configuring save_policy and tensorboard is supported")
        if self.socket:
            # In the user process
            self.socket.send(options)
        elif self._jupyter_agent:
            # Running in jupyter
            self._jupyter_agent.start()
            if options.get("save_policy"):
                self._jupyter_agent.rm.update_user_file_policy(
                    options["save_policy"])
            elif options.get("tensorboard"):
                self._jupyter_agent.rm.start_tensorboard_watcher(
                    options["tensorboard"]["logdir"], options["tensorboard"]["save"])
        elif self._run_manager:
            # Running in the wandb process, used for tfevents saving
            if options.get("save_policy"):
                self._run_manager.update_user_file_policy(
                    options["save_policy"])
        else:
            wandb.termerror(
                "wandb.init hasn't been called, can't configure run")

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
        run_id = environment.get(env.RUN_ID)
        resume = environment.get(env.RESUME)
        storage_id = environment.get(env.RUN_STORAGE_ID)
        mode = environment.get(env.MODE)
        api = InternalApi(environ=environment)
        disabled = api.disabled()
        if not mode and disabled:
            mode = "dryrun"
        elif disabled and mode != "dryrun":
            wandb.termwarn(
                "WANDB_MODE is set to run, but W&B was disabled.  Run `wandb on` to remove this message")
        elif disabled:
            wandb.termlog(
                'W&B is disabled in this directory.  Run `wandb on` to enable cloud syncing.')

        group = environment.get(env.RUN_GROUP)
        job_type = environment.get(env.JOB_TYPE)
        run_dir = environment.get(env.RUN_DIR)
        sweep_id = environment.get(env.SWEEP_ID)
        program = environment.get(env.PROGRAM)
        description = environment.get(env.DESCRIPTION)
        name = environment.get(env.NAME)
        notes = environment.get(env.NOTES)
        args = env.get_args(env=environment)
        wandb_dir = env.get_dir(env=environment)
        tags = env.get_tags(env=environment)
        # TODO(adrian): should pass environment into here as well.
        config = Config.from_environment_or_defaults()
        run = cls(run_id, mode, run_dir,
                  group, job_type, config,
                  sweep_id, storage_id, program=program, description=description,
                  args=args, wandb_dir=wandb_dir, tags=tags,
                  name=name, notes=notes,
                  resume=resume, api=api)

        return run

    @classmethod
    def from_directory(cls, directory, project=None, entity=None, run_id=None, api=None, ignore_globs=None):
        api = api or InternalApi()
        run_id = run_id or util.generate_id()
        run = Run(run_id=run_id, dir=directory)

        run_name = None
        project_from_meta = None
        snap = DirectorySnapshot(directory)
        meta = next((p for p in snap.paths if METADATA_FNAME in p), None)
        if meta:
            meta = json.load(open(meta))
            run_name = meta.get("name")
            project_from_meta = meta.get("project")

        project = project or project_from_meta or api.settings(
            "project") or run.auto_project_name(api=api)
        if project is None:
            raise ValueError("You must specify project")
        api.set_current_run_id(run_id)
        api.set_setting("project", project)
        if entity:
            api.set_setting("entity", entity)
        res = api.upsert_run(name=run_id, project=project, entity=entity, display_name=run_name)
        entity = res["project"]["entity"]["name"]
        wandb.termlog("Syncing {} to:".format(directory))
        try:
            wandb.termlog(res["displayName"] + " " + run.get_url(api))
        except CommError as e:
            wandb.termwarn(e.message)

        file_api = api.get_file_stream_api()
        file_api.start()
        paths = [os.path.relpath(abs_path, directory)
                 for abs_path in snap.paths if os.path.isfile(abs_path)]
        if ignore_globs:
            paths = set(paths)
            for g in ignore_globs:
                paths = paths - set(fnmatch.filter(paths, g))
            paths = list(paths)
        run_update = {"id": res["id"]}
        tfevents = sorted([p for p in snap.paths if ".tfevents." in p])
        history = next((p for p in snap.paths if HISTORY_FNAME in p), None)
        event = next((p for p in snap.paths if EVENTS_FNAME in p), None)
        config = next((p for p in snap.paths if CONFIG_FNAME in p), None)
        user_config = next(
            (p for p in snap.paths if USER_CONFIG_FNAME in p), None)
        summary = next((p for p in snap.paths if SUMMARY_FNAME in p), None)
        if history:
            wandb.termlog("Uploading history metrics")
            file_api.stream_file(history)
            snap.paths.remove(history)
        elif len(tfevents) > 0:
            from wandb import tensorflow as wbtf
            wandb.termlog("Found tfevents file, converting...")
            summary = {}
            for path in tfevents:
                filename = os.path.basename(path)
                namespace = path.replace(filename, "").replace(directory, "").strip(os.sep)
                summary.update(wbtf.stream_tfevents(path, file_api, run, namespace=namespace))
            for path in glob.glob(os.path.join(directory, "media/**/*"), recursive=True):
                if os.path.isfile(path):
                    paths.append(path)
        else:
            wandb.termerror(
                "No history or tfevents files found, only syncing files")
        if event:
            file_api.stream_file(event)
            snap.paths.remove(event)
        if config:
            run_update["config"] = util.load_yaml(
                open(config))
        elif user_config:
            # TODO: half backed support for config.json
            run_update["config"] = {k: {"value": v}
                                    for k, v in six.iteritems(user_config)}
        if isinstance(summary, dict):
            #TODO: summary should already have data_types converted here...
            run_update["summary_metrics"] = util.json_dumps_safer(summary)
        elif summary:
            run_update["summary_metrics"] = open(summary).read()
        if meta:
            if meta.get("git"):
                run_update["commit"] = meta["git"].get("commit")
                run_update["repo"] = meta["git"].get("remote")
            if meta.get("host"):
                run_update["host"] = meta["host"]
            run_update["program_path"] = meta["program"]
            run_update["job_type"] = meta.get("jobType")
            run_update["notes"] = meta.get("notes")
        else:
            run_update["host"] = run.host

        wandb.termlog("Updating run and uploading files")
        api.upsert_run(**run_update)
        pusher = FilePusher(api)
        for k in paths:
            path = os.path.abspath(os.path.join(directory, k))
            pusher.update_file(k, path)
            pusher.file_changed(k, path)
        pusher.finish()
        pusher.print_status()
        file_api.finish(0)
        # Remove temporary media images generated from tfevents
        if history is None and os.path.exists(os.path.join(directory, "media")):
            shutil.rmtree(os.path.join(directory, "media"))
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
        api = api or self.api
        project = api.settings('project')
        if project is None:
            project = self.auto_project_name(api)
        upsert_result = api.upsert_run(id=id or self.storage_id, name=self.id, commit=api.git.last_commit,
                                       project=project, entity=self.entity,
                                       group=self.group, tags=self.tags if len(
                                           self.tags) > 0 else None,
                                       config=self.config.as_dict(), description=self._name_and_description, host=self.host,
                                       program_path=program or self.program, repo=api.git.remote_url, sweep_name=self.sweep_id,
                                       display_name=self._name, notes=self.notes,
                                       summary_metrics=summary_metrics, job_type=self.job_type, num_retries=num_retries)
        self.storage_id = upsert_result['id']
        self.name = upsert_result.get('displayName')
        return upsert_result

    def set_environment(self, environment=None):
        """Set environment variables needed to reconstruct this object inside
        a user scripts (eg. in `wandb.init()`).
        """
        if environment is None:
            environment = os.environ
        environment[env.RUN_ID] = self.id
        environment[env.RESUME] = self.resume
        if self.storage_id:
            environment[env.RUN_STORAGE_ID] = self.storage_id
        environment[env.MODE] = self.mode
        environment[env.RUN_DIR] = self.dir

        if self.group:
            environment[env.RUN_GROUP] = self.group
        if self.job_type:
            environment[env.JOB_TYPE] = self.job_type
        if self.wandb_dir:
            environment[env.DIR] = self.wandb_dir
        if self.sweep_id is not None:
            environment[env.SWEEP_ID] = self.sweep_id
        if self.program is not None:
            environment[env.PROGRAM] = self.program
        if self.args is not None:
            environment[env.ARGS] = json.dumps(self.args)
        if self._name_and_description is not None:
            environment[env.DESCRIPTION] = self._name_and_description
        if self._name is not None:
            environment[env.NAME] = self._name
        if self.notes is not None:
            environment[env.NOTES] = self.notes
        if len(self.tags) > 0:
            environment[env.TAGS] = ",".join(self.tags)
        return environment

    def _mkdir(self):
        util.mkdir_exists_ok(self._dir)

    def project_name(self, api=None):
        api = api or self.api
        return api.settings('project') or self.auto_project_name(api) or "uncategorized"
        
    def _generate_query_string(self, api, params=None):
        """URL encodes dictionary of params"""

        params = params or {}

        if str(api.settings().get('anonymous', 'false')) == 'true':
            params['apiKey'] = api.api_key

        if not params:
            return ""
        return '?' + urllib.parse.urlencode(params)

    def _load_entity(self, api, network):
        if not api.api_key:
            raise CommError("Can't find API key, run wandb login or set WANDB_API_KEY")

        entity = api.settings('entity')
        if network:
            if api.settings('entity') is None:
                viewer = api.viewer()
                if viewer.get('entity'):
                    api.set_setting('entity', viewer['entity'])
        
            entity = api.settings('entity')
        
        if not entity:
            # This can happen on network failure
            raise CommError("Can't connect to network to query entity from API key")

        return entity

    def get_project_url(self, api=None, network=None, params=None):
        """Generate a url for a project.
        
        If network is false and entity isn't specified in the environment raises wandb.apis.CommError
        """
        params = params or {}
        api = api or self.api
        self._load_entity(api, network)

        return "{base}/{entity}/{project}{query_string}".format(
            base=api.app_url,
            entity=urllib.parse.quote_plus(api.settings('entity')),
            project=urllib.parse.quote_plus(self.project_name(api)),
            query_string=self._generate_query_string(api, params)
        )

    def get_url(self, api=None, network=True, params=None):
        """Generate a url for a run.
        
        If network is false and entity isn't specified in the environment raises wandb.apis.CommError
        """
        params = params or {}
        api = api or self.api
        self._load_entity(api, network)

        return "{base}/{entity}/{project}/runs/{run}{query_string}".format(
            base=api.app_url,
            entity=urllib.parse.quote_plus(api.settings('entity')),
            project=urllib.parse.quote_plus(self.project_name(api)),
            run=urllib.parse.quote_plus(self.id),
            query_string=self._generate_query_string(api, params)
        )
         

    def upload_debug(self):
        """Uploads the debug log to cloud storage"""
        if os.path.exists(self.log_fname):
            pusher = FilePusher(self.api)
            pusher.update_file("wandb-debug.log", self.log_fname)
            pusher.file_changed("wandb-debug.log", self.log_fname)
            pusher.finish()

    def __repr__(self):
        try:
            return "W&B Run: %s" % self.get_url()
        except CommError as e:
            return "W&B Error: %s" % e.message

    @property
    def name(self):
        if self._name is not None:
            return self._name
        elif self._name_and_description is not None:
            return self._name_and_description.split("\n")[0]
        else:
            return None

    @name.setter
    def name(self, name):
        self._name = name
        if self._name_and_description is not None:
            parts = self._name_and_description.split("\n", 1)
            parts[0] = name
            self._name_and_description = "\n".join(parts)

    @property
    def description(self):
        wandb.termwarn('Run.description is deprecated. Please use run.notes instead.')
        if self._name_and_description is None:
            self._name_and_description = ''
        parts = self._name_and_description.split("\n", 1)
        if len(parts) > 1:
            return parts[1]
        else:
            return ""

    @description.setter
    def description(self, desc):
        wandb.termwarn('Run.description is deprecated. Please use wandb.init(notes="long notes") instead.')
        if self._name_and_description is None:
            self._name_and_description = self._name or ""
        parts = self._name_and_description.split("\n", 1)
        if len(parts) == 1:
            parts.append("")
        parts[1] = desc
        self._name_and_description = "\n".join(parts)
        with open(self.description_path, 'w') as d_file:
            d_file.write(self._name_and_description)

    @property
    def host(self):
        return os.environ.get(env.HOST, socket.gethostname())

    @property
    def dir(self):
        return self._dir

    @property
    def log_fname(self):
        # TODO: we started work to log to a file in the run dir, but it had issues.
        # For now all logs goto the same place.
        return util.get_log_file_path()

    def enable_logging(self):
        """Enable logging to the global debug log.  This adds a run_id to the log,
        in case of muliple processes on the same machine.

        Currently no way to disable logging after it's enabled.
        """
        handler = logging.FileHandler(self.log_fname)
        handler.setLevel(logging.INFO)
        run_id = self.id

        class WBFilter(logging.Filter):
            def filter(self, record):
                record.run_id = run_id
                return True

        formatter = logging.Formatter(
            '%(asctime)s %(levelname)-7s %(threadName)-10s:%(process)d [%(run_id)s:%(filename)s:%(funcName)s():%(lineno)s] %(message)s')
        handler.setFormatter(formatter)
        handler.addFilter(WBFilter())

        root = logging.getLogger()
        root.addHandler(handler)

    @property
    def summary(self):
        if self._summary is None:
            self._summary = summary.FileSummary(self)
        return self._summary

    @property
    def has_summary(self):
        return self._summary or os.path.exists(os.path.join(self._dir, summary.SUMMARY_FNAME))

    def _history_added(self, row):
        self.summary.update(row, overwrite=False)

    @property
    def history(self):
        if self._history is None:
            jupyter_callback = self._jupyter_agent.start if self._jupyter_agent else None
            self._history = history.History(
                self, add_callback=self._history_added, jupyter_callback=jupyter_callback)
            if self._history._steps > 0:
                self.resumed = True
        return self._history

    @property
    def step(self):
        return self.history._steps

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
    def description_path(self):
        return os.path.join(self.dir, DESCRIPTION_FNAME)

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


def run_dir_path(run_id, dry=False):
    if dry:
        prefix = 'dryrun'
    else:
        prefix = 'run'
    time_str = datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    return os.path.join(wandb.wandb_dir(), '{}-{}-{}'.format(prefix, time_str, run_id))
