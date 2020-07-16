# -*- coding: utf-8 -*-
"""Run - Run object.

Manage wandb run.

"""

from __future__ import print_function

import json
import logging
import os
import platform
import shutil

import click
import wandb
from wandb.apis import internal, public
from wandb.data_types import _datatypes_set_callback
from wandb.util import sentry_set_scope, to_forward_slash_path
from wandb.viz import Visualize

from . import wandb_config
from . import wandb_history
from . import wandb_summary


logger = logging.getLogger("wandb")


class Run(object):
    def __init__(self):
        pass


class RunDummy(Run):
    def __init__(self):
        pass


class RunManaged(Run):
    def __init__(self, config=None, settings=None):
        self._config = wandb_config.Config()
        self._config._set_callback(self._config_callback)
        self.summary = wandb_summary.Summary()
        self.summary._set_callback(self._summary_callback)
        self.history = wandb_history.History()
        self.history._set_callback(self._history_callback)

        _datatypes_set_callback(self._datatypes_callback)

        self._settings = settings
        self._backend = None
        self._reporter = None
        self._data = dict()

        self._entity = None
        self._project = None
        self._group = None
        self._job_type = None
        self._run_id = settings.run_id
        self._name = None
        self._notes = None
        self._tags = None

        # Pull info from settings
        self._init_from_settings(settings)

        # Initial scope setup for sentry. This might get changed when the
        # actual run comes back.
        sentry_set_scope("user", self._entity, self._project)

        # Returned from backend send_run_sync, set from wandb_init?
        self._run_obj = None

        config = config or dict()
        wandb_key = "_wandb"
        config.setdefault(wandb_key, dict())
        config[wandb_key]["cli_version"] = wandb.__version__
        if settings.save_code and settings.code_program:
            config[wandb_key]["code_path"] = to_forward_slash_path(
                os.path.join("code", settings.code_program)
            )
        self._config._update(config)

    def _init_from_settings(self, settings):
        if settings.entity is not None:
            self._entity = settings.entity
        if settings.project is not None:
            self._project = settings.project
        if settings.run_group is not None:
            self._group = settings.run_group
        if settings.job_type is not None:
            self._job_type = settings.job_type
        if settings.run_name is not None:
            self._name = settings.run_name
        if settings.run_notes is not None:
            self._notes = settings.run_notes
        if settings.run_tags is not None:
            self._tags = settings.run_tags

    def _make_proto_run(self, run):
        """Populate protocol buffer RunData for interface/interface."""
        if self._entity is not None:
            run.entity = self._entity
        if self._project is not None:
            run.project = self._project
        if self._group is not None:
            run.run_group = self._group
        if self._job_type is not None:
            run.job_type = self._job_type
        if self._run_id is not None:
            run.run_id = self._run_id
        if self._name is not None:
            run.display_name = self._name
        if self._notes is not None:
            run.notes = self._notes
        if self._tags is not None:
            for tag in self._tags:
                run.tags.append(tag)
        # Note: run.config is set in interface/interface:_make_run()

    def __getstate__(self):
        pass

    def __setstate__(self, state):
        pass

    @property
    def dir(self):
        return self._settings.files_dir

    @property
    def config(self):
        return self._config

    @property
    def name(self):
        if not self._run_obj:
            return None
        return self._run_obj.display_name

    @property
    def id(self):
        return self._run_id

    def project_name(self, api=None):
        # TODO(jhr): this is probably not right needed by dataframes?
        # api = api or self.api
        # return (api.settings('project') or self.auto_project_name(api) or
        #         "uncategorized")
        return self._project

    @property
    def entity(self):
        return self._entity

    # def _repr_html_(self):
    #     url = "https://app.wandb.test/jeff/uncategorized/runs/{}".format(
    #       self.run_id)
    #     style = "border:none;width:100%;height:400px"
    #     s = "<h1>Run({})</h1><iframe src=\"{}\" style=\"{}\"></iframe>".format(
    #       self.run_id, url, style)
    #     return s

    def _repr_mimebundle_(self, include=None, exclude=None):
        url = self._get_run_url()
        style = "border:none;width:100%;height:400px"
        note = ""
        if include or exclude:
            note = "(DEBUG: include={}, exclude={})".format(include, exclude)
        s = '<h1>Run({})</h1><p>{}</p><iframe src="{}" style="{}"></iframe>'.format(
            self._run_id, note, url, style
        )
        return {"text/html": s}

    def _config_callback(self, key=None, val=None, data=None):
        logger.info("config_cb %s %s %s", key, val, data)
        self._backend.interface.send_config(data)

    def _summary_callback(self, key=None, val=None, data=None):
        self._backend.interface.send_summary(data)

    def _datatypes_callback(self, fname):
        files = dict(files=[(fname,)])
        self._backend.interface.send_files(files)

    def _history_callback(self, row=None):

        # TODO(jhr): move visualize hack somewhere else
        visualize_persist_config = False
        for k in row:
            if isinstance(row[k], Visualize):
                if "viz" not in self._config["_wandb"]:
                    self._config["_wandb"]["viz"] = dict()
                self._config["_wandb"]["viz"][k] = {
                    "id": row[k].viz_id,
                    "historyFieldSettings": {"key": k, "x-axis": "_step"},
                }
                row[k] = row[k].value
                visualize_persist_config = True
        if visualize_persist_config:
            self._config_callback(data=self._config._as_dict())

        self.summary.update(row)
        self._backend.interface.send_history(row)

    def _set_backend(self, backend):
        self._backend = backend

    def _set_reporter(self, reporter):
        self._reporter = reporter

    def _set_run_obj(self, run_obj):
        self._run_obj = run_obj
        # TODO: It feels weird to call this twice..
        sentry_set_scope("user", run_obj.entity, run_obj.project, self._get_run_url())

    def _add_singleton(self, type, key, value):
        """Stores a singleton item to wandb config.

        A singleton in this context is a piece of data that is continually
        logged with the same value in each history step, but represented
        as a single item in the config.

        We do this to avoid filling up history with a lot of repeated uneccessary data

        Add singleton can be called many times in one run and it will only be
        updated when the value changes. The last value logged will be the one
        persisted to the server"""
        value_extra = {"type": type, "key": key, "value": value}

        if type not in self.config["_wandb"]:
            self.config["_wandb"][type] = {}

        if type in self.config["_wandb"][type]:
            old_value = self.config["_wandb"][type][key]
        else:
            old_value = None

        if value_extra != old_value:
            self.config["_wandb"][type][key] = value_extra
            self.config.persist()

    def log(self, data, step=None, commit=True, sync=None):
        # TODO(cling): sync is a noop for now
        if commit:
            self.history._row_add(data)
        else:
            self.history._row_update(data)

    def join(self):
        self._backend.cleanup()

    def _get_project_url(self):
        s = self._settings
        r = self._run_obj
        app_url = s.base_url.replace("//api.", "//app.")
        url = "{}/{}/{}".format(app_url, r.entity, r.project)
        return url

    def _get_run_url(self):
        s = self._settings
        r = self._run_obj
        app_url = s.base_url.replace("//api.", "//app.")
        url = "{}/{}/{}/runs/{}".format(app_url, r.entity, r.project, r.run_id)
        return url

    def _get_run_name(self):
        r = self._run_obj
        return r.display_name

    def _display_run(self):
        emojis = dict(star="", broom="", rocket="")
        if platform.system() != "Windows":
            emojis = dict(star="⭐️", broom="🧹", rocket="🚀")
        project_url = self._get_project_url()
        run_url = self._get_run_url()
        wandb.termlog(
            "{} View project at {}".format(
                emojis.get("star", ""),
                click.style(project_url, underline=True, fg="blue"),
            )
        )
        wandb.termlog(
            "{} View run at {}".format(
                emojis.get("rocket", ""),
                click.style(run_url, underline=True, fg="blue"),
            )
        )

    def on_start(self):
        wandb.termlog("Tracking run with wandb version {}".format(wandb.__version__))
        if self._run_obj:
            run_state_str = "Syncing run"
            run_name = self._get_run_name()
            wandb.termlog(
                "{} {}".format(run_state_str, click.style(run_name, fg="yellow"))
            )
            self._display_run()
        print("")

    def on_finish(self):
        # check for warnings and errors, show log file locations
        # if self._run_obj:
        #    self._display_run()
        if self._reporter:
            warning_lines = self._reporter.warning_lines
            if warning_lines:
                wandb.termlog("Warnings:")
                for line in warning_lines:
                    wandb.termlog(line)
                if len(warning_lines) < self._reporter.warning_count:
                    wandb.termlog("More warnings")

            error_lines = self._reporter.error_lines
            if error_lines:
                wandb.termlog("Errors:")
                for line in error_lines:
                    wandb.termlog(line)
                if len(error_lines) < self._reporter.error_count:
                    wandb.termlog("More errors")
        if self._settings.log_user:
            wandb.termlog(
                "Find user logs for this run at: {}".format(self._settings.log_user)
            )
        if self._settings.log_internal:
            wandb.termlog(
                "Find internal logs for this run at: {}".format(
                    self._settings.log_internal
                )
            )
        if self._run_obj:
            run_url = self._get_run_url()
            run_name = self._get_run_name()
            wandb.termlog(
                "Synced {}: {}".format(
                    click.style(run_name, fg="yellow"), click.style(run_url, fg="blue")
                )
            )

    def _save_job_spec(self):
        envdict = dict(python="python3.6", requirements=[],)
        varsdict = {"WANDB_DISABLE_CODE": "True"}
        source = dict(
            git="git@github.com:wandb/examples.git", branch="master", commit="bbd8d23",
        )
        execdict = dict(
            program="train.py",
            directory="keras-cnn-fashion",
            envvars=varsdict,
            args=[],
        )
        configdict = (dict(self._config),)
        artifactsdict = dict(dataset="v1",)
        inputdict = dict(config=configdict, artifacts=artifactsdict,)
        job_spec = {
            "kind": "WandbJob",
            "version": "v0",
            "environment": envdict,
            "source": source,
            "exec": execdict,
            "input": inputdict,
        }

        s = json.dumps(job_spec, indent=4)
        spec_filename = "wandb-jobspec.json"
        with open(spec_filename, "w") as f:
            print(s, file=f)
        self.save(spec_filename)

    def save(self, path):
        # TODO(jhr): this only works with files at root level of files dir
        fname = os.path.basename(path)

        if os.path.exists(path):
            dest = os.path.join(self._settings.files_dir, fname)
            logger.info("Saving from %s to %s", path, dest)
            shutil.copyfile(path, dest)
        else:
            logger.info("file not found: %s", path)

        files = dict(files=[(fname,)])
        self._backend.interface.send_files(files)

    # NB: there is a copy of this in wandb_watch.py with the same signature
    def watch(self, models, criterion=None, log="gradients", log_freq=100, idx=None):
        logger.info("Watching")
        # wandb.run.watch(watch)

    def use_artifact(self, artifact_or_name, type=None, aliases=None):
        """ Declare an artifact as an input to a run, call `download` or `file` on \
        the returned object to get the contents locally.

        Args:
            artifact_or_name (str or Artifact): An artifact name.
            May be prefixed with entity/project. Valid names
                can be in the following forms:
                    name:version
                    name:alias
                    digest
                You can also pass an Artifact object created by calling `wandb.Artifact`
            type (str, optional): The type of artifact to use.
            aliases (list, optional): Aliases to apply to this artifact
        Returns:
            A :obj:`Artifact` object.
        """
        r = self._run_obj
        api = internal.Api(default_settings={"entity": r.entity, "project": r.project})
        api.set_current_run_id(self.id)

        if isinstance(artifact_or_name, str):
            name = artifact_or_name
            if type is None:
                raise ValueError("type required")
            public_api = public.Api()
            artifact = public_api.artifact(type=type, name=name)
            if type is not None and type != artifact.type:
                raise ValueError(
                    "Supplied type {} does not match type {} of artifact {}".format(
                        type, artifact.type, artifact.name
                    )
                )
            api.use_artifact(artifact.id)
            return artifact
        else:
            artifact = artifact_or_name
            if type is not None:
                raise ValueError("cannot specify type when passing Artifact object")
            if isinstance(aliases, str):
                aliases = [aliases]
            if isinstance(artifact_or_name, wandb.Artifact):
                artifact.finalize()
                self._backend.interface.send_artifact(
                    self, artifact, aliases, is_user_created=True, use_after_commit=True
                )
                return artifact
            elif isinstance(artifact, public.Artifact):
                api.use_artifact(artifact.id)
                return artifact
            else:
                raise ValueError(
                    'You must pass an artifact name (e.g. "pedestrian-dataset:v1"), an instance of wandb.Artifact, or wandb.Api().artifact() to use_artifact'  # noqa: E501
                )

    def log_artifact(self, artifact_or_path, name=None, type=None, aliases=None):
        """ Declare an artifact as output of a run.

        Args:
            artifact_or_path (str or Artifact): A path to the contents of this artifact,
                can be in the following forms:
                    /local/directory
                    /local/directory/file.txt
                    s3://bucket/path
                You can also pass an Artifact object created by calling
                `wandb.Artifact`.
            name (str, optional): An artifact name. May be prefixed with entity/project.
                Valid names can be in the following forms:
                    name:version
                    name:alias
                    digest
                This will default to the basename of the path prepended with the current
                run id  if not specified.
            type (str): The type of artifact to log, examples include "dataset", "model"
            aliases (list, optional): Aliases to apply to this artifact,
                defaults to ["latest"]
        Returns:
            A :obj:`Artifact` object.
        """
        aliases = aliases or ["latest"]
        if isinstance(artifact_or_path, str):
            if name is None:
                name = "run-%s-%s" % (self.id, os.path.basename(artifact_or_path))
            artifact = wandb.Artifact(name, type)
            if os.path.isfile(artifact_or_path):
                artifact.add_file(artifact_or_path)
            elif os.path.isdir(artifact_or_path):
                artifact.add_dir(artifact_or_path)
            elif "://" in artifact_or_path:
                artifact.add_reference(artifact_or_path)
            else:
                raise ValueError(
                    "path must be a file, directory or external"
                    "reference like s3://bucket/path"
                )
        else:
            artifact = artifact_or_path
        if not isinstance(artifact, wandb.Artifact):
            raise ValueError(
                "You must pass an instance of wandb.Artifact or a "
                "valid file path to log_artifact"
            )
        if isinstance(aliases, str):
            aliases = [aliases]
        artifact.finalize()
        self._backend.interface.send_artifact(self, artifact, aliases)
        return artifact
