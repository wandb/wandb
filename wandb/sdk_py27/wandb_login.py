# -*- coding: utf-8 -*-
"""
login.
"""

import requests
import logging

import wandb

logger = logging.getLogger("wandb")


def login():
    if is_logged_in():
        return True
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
