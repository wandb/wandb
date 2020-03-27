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
        self.config = wandb_config.Config()
        self.config._set_callback(self._config_callback)
        self.summary = wandb_summary.Summary()
        self.summary._set_callback(self._summary_callback)
        self._history = wandb_history.History()
        self._history._set_callback(self._history_callback)

        self._settings = settings
        self._backend = None
        self._data = dict()
        self.run_id = generate_id()

        # Returned from backend send_run_sync, set from wandb_init?
        self._run_obj = None

        config = config or dict()
        wandb_key = "_wandb"
        config.setdefault(wandb_key, dict(desc=None, value=dict()))
        config[wandb_key]["value"]["cli_version"] = wandb.__version__
        if config:
            self.config.update(config)

    def __getstate__(self):
        pass

    def __setstate__(self, state):
        pass

    @property
    def dir(self):
        return self._settings.files_dir

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
            self.run_id, note, url, style)
        return {"text/html": s}

    def _config_callback(self, key=None, val=None, data=None):
        logger.info("config_cb %s %s %s", key, val, data)
        c = dict(run_id=self.run_id, data=data)
        self._backend.interface.send_config(c)

    def _summary_callback(self, key=None, val=None, data=None):
        s = dict(run_id=self.run_id, data=data)
        self._backend.interface.send_summary(s)

    def _history_callback(self, row=None):
        self.summary.update(row)
        self._backend.interface.send_log(row)

    def _set_backend(self, backend):
        self._backend = backend

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
        url = "{}/{}/{}/runs/{}".format(app_url, r.team, r.project, r.run_id)
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
        if self._run_obj:
            self._display_run()

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
        configdict = dict(self.config),
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
