# -*- coding: utf-8 -*-

import wandb
from . import wandb_config

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
        self._settings = settings
        self._backend = None
        self._data = dict()
        self.run_id = generate_id()
        self._step = 0
        self._run_obj = None
        self._run_dir = None

        if config:
            self.config.update(config)

    def __getstate__(self):
        pass

    def __setstate__(self, state):
        pass

    @property
    def dir(self):
        return self._run_dir

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
        self._backend.send_config(c)

    def _set_backend(self, backend):
        self._backend = backend

    def _set_run_obj(self, run_obj):
        self._run_obj = run_obj

    def log(self, data, step=None, commit=True):
        if commit:
            self._data["_step"] = self._step
            self._step += 1
            self._data.update(data)
            self._backend.send_log(self._data)
            self._data = dict()
        else:
            self._data.update(data)

    def join(self):
        self._backend.cleanup()

    @property
    def dir(self):
        return "run_dir"

    @property
    def summary(self):
        return dict()

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
        artifactsdict = dict(
                dataset="v1",
                )
        inputdict = dict(
                config=configdict,
                artifacts=artifactsdict,
                )
        job_spec = dict(
                kind="WandbJob",
                version="v0",
                environment=envdict,
                source=source,
                exec=execdict,
                input=inputdict,
                )

        s = json.dumps(job_spec, indent=4)
        spec_filename = "wandb-jobspec.json"
        with open(spec_filename, "w") as f:
            print(s, file=f)
        self.save(spec_filename)
        

    def save(self, path):
        orig_path = path
        # super hacky
        if not os.path.exists(path):
            path = os.path.join("run_dir", path)
        if not os.path.exists(path):
            logger.info("Ignoring file: %s", orig_path)
            return

        # whitelist = [ "save-test.txt", ]
        # if path not in whitelist:
        #    return

        fname = os.path.basename(path)
        dest = os.path.join(self._settings.files_dir, fname)
        logger.info("Saving from %s to %s", path, dest)
        shutil.copyfile(path, dest)
        files = dict(files=[fname])
        self._backend.send_files(files)
