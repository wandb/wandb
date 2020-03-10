# -*- coding: utf-8 -*-

import wandb
from . import wandb_config
import shortuuid  # type: ignore
import click


def generate_id():
    # ~3t run ids (36**8)
    run_gen = shortuuid.ShortUUID(
        alphabet=list("0123456789abcdefghijklmnopqrstuvwxyz"))
    return run_gen.random(8)


class Run(object):
    def __init__(self, config=None, settings=None):
        self.config = wandb_config.Config()
        self._settings = settings
        self._backend = None
        self._data = dict()
        self.run_id = generate_id()
        self._step = 0
        self._run_obj = None

        if config:
            self.config.update(config)

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
        self._backend.join()

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
        emojis = dict(star="⭐️", broom="🧹", rocket="🚀")
        url = self._get_run_url()
        wandb.termlog("{} View run at {}".format(
            emojis.get("rocket", ""),
            click.style(url, underline=True, fg='blue')))

    def on_start(self):
        if self._run_obj:
            self._display_run()

    def on_finish(self):
        pass
