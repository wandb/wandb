# -*- coding: utf-8 -*-
"""
login.
"""

from __future__ import print_function

import logging

import click
import requests
import wandb
from wandb.apis import InternalApi
from wandb.lib import apikey

logger = logging.getLogger("wandb")


def _validate_anonymous_setting(anon_str):
    return anon_str in ["must", "allow", "never"]


def login(api=None, relogin=None, key=None, anonymous=None):
    """Log in to W&B.

    Args:
        settings (dict, optional): Override settings.
        relogin (bool, optional): If true, will re-prompt for API key.
        anonymous (string, optional): Can be "must", "allow", or "never".
            If set to "must" we'll always login anonymously, if set to
            "allow" we'll only create an anonymous user if the user
            isn't already logged in.
    Returns:
        None
    """
    if wandb.run is not None:
        wandb.termwarn("Calling wandb.login() after wandb.init() is a no-op.")
        return

    settings = {}
    api = api or InternalApi()

    if anonymous is not None:
        # TODO: Move this check into wandb_settings probably.
        if not _validate_anonymous_setting(anonymous):
            wandb.termwarn(
                "Invalid value passed for argument `anonymous` to "
                "wandb.login(). Can be 'must', 'allow', or 'never'."
            )
            return
        settings.update({"anonymous": anonymous})

    # Note: This won't actually do anything if called from a codepath where
    # wandb.setup was previously called. If wandb.setup is called further up,
    # you must make sure the anonymous setting (and any other settings) are
    # already properly set up there.
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

    jupyter = settings.jupyter or False
    if key:
        if jupyter:
            wandb.termwarn(
                (
                    "If you're specifying your api key in code, ensure this "
                    "code is not shared publically.\nConsider setting the "
                    "WANDB_API_KEY environment variable, or running "
                    "`wandb login` from the command line."
                )
            )
        apikey.write_key(settings, key)
    else:
        apikey.prompt_api_key(settings, api=api)
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
