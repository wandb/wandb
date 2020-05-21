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
from wandb.data_types import _datatypes_set_callback

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

        # Returned from backend send_run_sync, set from wandb_init?
        self._run_obj = None

        config = config or dict()
        wandb_key = "_wandb"
        config.setdefault(wandb_key, dict())
        config[wandb_key]["cli_version"] = wandb.__version__
        if config:
            self._config.update(config)

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
        self.summary.update(row)
        self._backend.interface.send_history(row)

    def _set_backend(self, backend):
        self._backend = backend

    def _set_reporter(self, reporter):
        self._reporter = reporter

    def _set_run_obj(self, run_obj):
        self._run_obj = run_obj

    def log(self, data, step=None, commit=True):
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
