#!/usr/bin/env python

"""All of W&B's environment variables

Getters and putters for all of them should go here. That
way it'll be easier to avoid typos with names and be
consistent about environment variables' semantics.

Environment variables are not the authoritative source for
these values in many cases.
"""

import os

CONFIG_PATHS = 'WANDB_CONFIG_PATHS'
SHOW_RUN = 'WANDB_SHOW_RUN'
DEBUG = 'WANDB_DEBUG'
INITED = 'WANDB_INITED'
DIR = 'WANDB_DIR'
DESCRIPTION = 'WANDB_DESCRIPTION'
PROJECT = 'WANDB_PROJECT'
ENTITY = 'WANDB_ENTITY'
BASE_URL = 'WANDB_BASE_URL'
RUN = 'WANDB_RUN'
IGNORE = 'WANDB_IGNORE_GLOBS'
ERROR_REPORTING = 'WANDB_ERROR_REPORTING'


def is_debug():
    return bool(get_debug())


def get_debug(default=None, env=None):
    if env is None:
        env = os.environ

    return env.get(DEBUG, default)


def error_reporting_enabled():
    return bool(get_error_reporting())


def get_error_reporting(default=True, env=None):
    if env is None:
        env = os.environ

    return env.get(ERROR_REPORTING, default)


def get_run(default=None, env=None):
    if env is None:
        env = os.environ

    return env.get(RUN, default)


def get_ignore(default=None, env=None):
    if env is None:
        env = os.environ

    if env.get(IGNORE, default):
        return env.get(IGNORE, default).split(",")
    else:
        return []


def get_project(default=None, env=None):
    if env is None:
        env = os.environ

    return env.get(PROJECT, default)


def get_entity(default=None, env=None):
    if env is None:
        env = os.environ

    return env.get(ENTITY, default)


def get_base_url(default=None, env=None):
    if env is None:
        env = os.environ

    return env.get(BASE_URL, default)


def get_show_run(default=None, env=None):
    if env is None:
        env = os.environ

    return bool(env.get(SHOW_RUN, default))


def get_description(default=None, env=None):
    if env is None:
        env = os.environ

    return env.get(DESCRIPTION, default)


def get_dir(default=None, env=None):
    if env is None:
        env = os.environ
    return env.get(DIR, default)


def get_config_paths():
    pass
