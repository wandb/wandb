# -*- coding: utf-8 -*-
"""Run - Run object.

Manage wandb run.

"""

from __future__ import print_function

import wandb
from . import wandb_config
from . import wandb_summary
from . import wandb_history

import shortuuid  # type: ignore
import click
import platform
import shutil
import logging
import os
import json

logger = logging.getLogger("wandb")


def generate_id():
    # ~3t run ids (36**8)
    run_gen = shortuuid.ShortUUID(
        alphabet=list("0123456789abcdefghijklmnopqrstuvwxyz"))
    return run_gen.random(8)


class Run(object):
    def __init__(self, config=None, settings=None):
        self._config = wandb_config.Config()
        self._config._set_callback(self._config_callback)
        self.summary = wandb_summary.Summary()
        self.summary._set_callback(self._summary_callback)
        self._history = wandb_history.History()
        self._history._set_callback(self._history_callback)

        self._settings = settings
        self._backend = None
        self._reporter = None
        self._data = dict()

        self._entity = None
        self._project = None
        self._group = None
        self._job_type = None
        self._run_id = generate_id()
        self._name = None
        self._notes = None
        self._tags = None

        # Pull info from settings
        self._init_from_settings(settings)

        # Returned from backend send_run_sync, set from wandb_init?
        self._run_obj = None

        config = config or dict()
        wandb_key = "_wandb"
        config.setdefault(wandb_key, dict(desc=None, value=dict()))
        config[wandb_key]["value"]["cli_version"] = wandb.__version__
        if config:
            self._config.update(config)

    def _init_from_settings(self, settings):
        if settings.entity is not None:
            self._entity = settings.entity
        if settings.project is not None:
            self._project = settings.project
        if settings.group is not None:
            self._group = settings.group
        if settings.job_type is not None:
            self._job_type = settings.job_type
        if settings.run_name is not None:
            self._name = settings.run_name
        if settings.run_notes is not None:
            self._notes = settings.run_notes
        if settings.run_tags is not None:
            self._tags = settings.run_tags

    def _make_proto_run(self, run):
        if self._entity is not None:
            run.entity = self._entity
        if self._project is not None:
            run.project = self._project
        if self._group is not None:
            run.group = self._group
        if self._job_type is not None:
            run.job_type = self._job_type
        if self._run_id is not None:
            run.run_id = self._run_id
        if self._name is not None:
            run.name = self._name
        if self._notes is not None:
            run.notes = self._notes
        if self._tags is not None:
            for tag in self._tags:
                run.tags.append(tag)
        if self._config is not None:
            run.config_json = json.dumps(self._config._as_dict())

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
        return self._run_obj.name

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
        s = "<h1>Run({})</h1><p>{}</p><iframe src=\"{}\" style=\"{}\"></iframe>".format(
            self._run_id, note, url, style)
        return {"text/html": s}

    def _config_callback(self, key=None, val=None, data=None):
        logger.info("config_cb %s %s %s", key, val, data)
        c = dict(run_id=self._run_id, data=data)
        self._backend.interface.send_config(c)

    def _summary_callback(self, key=None, val=None, data=None):
        s = dict(run_id=self._run_id, data=data)
        self._backend.interface.send_summary(s)

    def _history_callback(self, row=None):
        self.summary.update(row)
        self._backend.interface.send_log(row)

    def _set_backend(self, backend):
        self._backend = backend

    def _set_reporter(self, reporter):
        self._reporter = reporter

    def _set_run_obj(self, run_obj):
        self._run_obj = run_obj

    def log(self, data, step=None, commit=True):
        if commit:
            self._history._row_add(data)
        else:
            self._history._row_update(data)

    def join(self):
        self._backend.cleanup()

    def _get_run_url(self):
        s = self._settings
        r = self._run_obj
        app_url = s.base_url.replace("//api.", "//app.")
        url = "{}/{}/{}/runs/{}".format(app_url, r.entity, r.project, r.run_id)
        return url

    def _display_run(self):
        emojis = dict(star="", broom="", rocket="")
        if platform.system() != "Windows":
            emojis = dict(star="⭐️", broom="🧹", rocket="🚀")
        url = self._get_run_url()
        wandb.termlog("{} View run at {}".format(
            emojis.get("rocket", ""),
            click.style(url, underline=True, fg='blue')))

    def on_start(self):
        if self._run_obj:
            self._display_run()

    def on_finish(self):
        # check for warnings and errors, show log file locations
        if self._run_obj:
            self._display_run()
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
            wandb.termlog("Find user logs for this run at: {}".format(
                self._settings.log_user))
        if self._settings.log_internal:
            wandb.termlog("Find internal logs for this run at: {}".format(
                self._settings.log_internal))

    def _save_job_spec(self):
        envdict = dict(
            python="python3.6",
            requirements=[],
        )
        varsdict = {"WANDB_DISABLE_CODE": "True"}
        source = dict(
            git="git@github.com:wandb/examples.git",
            branch="master",
            commit="bbd8d23",
        )
        execdict = dict(
            program="train.py",
            directory="keras-cnn-fashion",
            envvars=varsdict,
            args=[],
        )
        configdict = dict(self._config),
        artifactsdict = dict(dataset="v1", )
        inputdict = dict(
            config=configdict,
            artifacts=artifactsdict,
        )
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
        fname = os.path.basename(path)

        if os.path.exists(path):
            dest = os.path.join(self._settings.files_dir, fname)
            logger.info("Saving from %s to %s", path, dest)
            shutil.copyfile(path, dest)
        else:
            logger.info("file not found yet: %s", path)

        files = dict(files=[fname])
        self._backend.interface.send_files(files)

    # NB: there is a copy of this in wand_wach with the same signature
    def watch(self,
              models,
              criterion=None,
              log="gradients",
              log_freq=100,
              idx=None):
        logger.info("Watching")
        #wandb.run.watch(watch)
