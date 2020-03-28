# -*- coding: utf-8 -*-
"""
login.
"""

from __future__ import print_function

import requests
import logging
from prompt_toolkit import prompt  # type: ignore
import getpass

import wandb
from wandb.util import apikey

logger = logging.getLogger("wandb")


def _get_python_type():
    try:
        if 'terminal' in get_ipython().__module__:
            return 'ipython'
        else:
            return 'jupyter'
    except (NameError, AttributeError):
        return "python"


def login(settings=None):
    if is_logged_in():
        return

    if not settings:
        wl = wandb.setup()
        settings = wl.settings()

    app_url = settings.base_url.replace("//api.", "//app.")
    in_jupyter = _get_python_type() != "python"
    if in_jupyter:
        print("Go to this URL in a browser: {}/authorize\n".format(app_url))
        key = getpass.getpass("Enter your authorization code:\n")
    else:
        print("Go to this URL in a browser: {}/authorize\n".format(app_url))
        key = prompt(u'Enter api key: ', is_password=True)

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
    if not settings:
        wl = wandb.setup()
        settings = wl.settings()
    return api_key(settings=settings) is not None
