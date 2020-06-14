# -*- coding: utf-8 -*-
"""
login.
"""

from __future__ import print_function

import getpass
import logging

import click
from prompt_toolkit import prompt  # type: ignore
import requests
import wandb
from wandb.lib import apikey

logger = logging.getLogger("wandb")


def _get_python_type():
    try:
        if "terminal" in get_ipython().__module__:
            return "ipython"
        else:
            return "jupyter"
    except (NameError, AttributeError):
        return "python"


def login(settings=None, relogin=None):
    wl = wandb.setup(settings=settings)
    settings = wl.settings()

    active_entity = None
    if is_logged_in():
        active_entity = wl._get_entity()
    if active_entity and not relogin:
        login_state_str = "Currently logged in as:"
        login_info_str = "(use `wandb login --relogin` to force relogin)"
        wandb.termlog(
            "{} {} {}".format(
                login_state_str, click.style(active_entity, fg="yellow"), login_info_str
            )
        )
        return

    app_url = settings.base_url.replace("//api.", "//app.")
    # TODO(jhr): use settings object
    in_jupyter = _get_python_type() != "python"
    authorize_str = "Go to this URL in a browser"
    authorize_link_str = "{}/authorize".format(app_url)
    if in_jupyter:
        print("{}: {}\n".format(authorize_str, authorize_link_str))
        key = getpass.getpass("Enter your authorization code:\n")
    else:
        wandb.termlog(
            "{}: {}".format(authorize_str, click.style(authorize_link_str, fg="blue"))
        )
        key = prompt(u"Enter api key: ", is_password=True)

    apikey.write_key(settings, key)
    return


def api_key(settings=None):
    if not settings:
        wl = wandb.setup()
        settings = wl.settings()
    if settings.api_key:
        return settings.api_key
    auth = requests.utils.get_netrc_auth(settings.base_url)
    if auth:
        return auth[-1]
    return None


def is_logged_in(settings=None):
    wl = wandb.setup(settings=settings)
    settings = wl.settings()
    return api_key(settings=settings) is not None
