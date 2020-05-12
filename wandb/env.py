#!/usr/bin/env python

"""All of W&B's environment variables

Getters and putters for all of them should go here. That
way it'll be easier to avoid typos with names and be
consistent about environment variables' semantics.

Environment variables are not the authoritative source for
these values in many cases.
"""

import os
import sys
import json
from distutils.util import strtobool

CONFIG_PATHS = 'WANDB_CONFIG_PATHS'
SHOW_RUN = 'WANDB_SHOW_RUN'
DEBUG = 'WANDB_DEBUG'
SILENT = 'WANDB_SILENT'
INITED = 'WANDB_INITED'
DIR = 'WANDB_DIR'
# Deprecate DESCRIPTION in a future release
DESCRIPTION = 'WANDB_DESCRIPTION'
NAME = 'WANDB_NAME'
NOTEBOOK_NAME = 'WANDB_NOTEBOOK_NAME'
NOTES = 'WANDB_NOTES'
USERNAME = 'WANDB_USERNAME'
USER_EMAIL = 'WANDB_USER_EMAIL'
PROJECT = 'WANDB_PROJECT'
ENTITY = 'WANDB_ENTITY'
BASE_URL = 'WANDB_BASE_URL'
PROGRAM = 'WANDB_PROGRAM'
ARGS = 'WANDB_ARGS'
MODE = 'WANDB_MODE'
RESUME = 'WANDB_RESUME'
RUN_ID = 'WANDB_RUN_ID'
RUN_STORAGE_ID = 'WANDB_RUN_STORAGE_ID'
RUN_GROUP = 'WANDB_RUN_GROUP'
RUN_DIR = 'WANDB_RUN_DIR'
SWEEP_ID = 'WANDB_SWEEP_ID'
HTTP_TIMEOUT = 'WANDB_HTTP_TIMEOUT'
API_KEY = 'WANDB_API_KEY'
JOB_TYPE = 'WANDB_JOB_TYPE'
DISABLE_CODE = 'WANDB_DISABLE_CODE'
SAVE_CODE = 'WANDB_SAVE_CODE'
TAGS = 'WANDB_TAGS'
IGNORE = 'WANDB_IGNORE_GLOBS'
ERROR_REPORTING = 'WANDB_ERROR_REPORTING'
DOCKER = 'WANDB_DOCKER'
AGENT_REPORT_INTERVAL = 'WANDB_AGENT_REPORT_INTERVAL'
AGENT_KILL_DELAY = 'WANDB_AGENT_KILL_DELAY'
AGENT_DISABLE_FLAPPING = 'WANDB_AGENT_DISABLE_FLAPPING'
CRASH_NOSYNC_TIME = 'WANDB_CRASH_NOSYNC_TIME'
MAGIC = 'WANDB_MAGIC'
HOST = 'WANDB_HOST'
ANONYMOUS = 'WANDB_ANONYMOUS'
JUPYTER = 'WANDB_JUPYTER'
CONFIG_DIR = 'WANDB_CONFIG_DIR'
PROGRAM = 'WANDB_PROGRAM'


def immutable_keys():
    """These are env keys that shouldn't change within a single process.  We use this to maintain
    certain values between multiple calls to wandb.init within a single process."""
    return [DIR, ENTITY, PROJECT, API_KEY, IGNORE, DISABLE_CODE, DOCKER, MODE, BASE_URL,
            ERROR_REPORTING, CRASH_NOSYNC_TIME, MAGIC, USERNAME, USER_EMAIL, DIR, SILENT, CONFIG_PATHS,
            ANONYMOUS, RUN_GROUP, JOB_TYPE, TAGS, RESUME, AGENT_REPORT_INTERVAL, HTTP_TIMEOUT,
            HOST, SAVE_CODE]


def _env_as_bool(var, default=None, env=None):
    if env is None:
        env = os.environ
    val = env.get(var, default)
    try:
        val = bool(strtobool(val))
    except (AttributeError, ValueError):
        pass
    return val if isinstance(val, bool) else False


def is_debug(default=None, env=None):
    return _env_as_bool(DEBUG, default=default, env=env)


def error_reporting_enabled():
    return _env_as_bool(ERROR_REPORTING, default=True)

def should_save_code():
    save_code = _env_as_bool(SAVE_CODE, default=False)
    code_disabled = _env_as_bool(DISABLE_CODE, default=False)
    # SAVE_CODE takes precedence over DISABLE_CODE
    return save_code and not code_disabled

def get_error_reporting(default=True, env=None):
    if env is None:
        env = os.environ

    return env.get(ERROR_REPORTING, default)


def get_run(default=None, env=None):
    if env is None:
        env = os.environ

    return env.get(RUN_ID, default)


def get_args(default=None, env=None):
    if env is None:
        env = os.environ
    if env.get(ARGS):
        try:
            return json.loads(env.get(ARGS, "[]"))
        except ValueError:
            return None
    else:
        return default or sys.argv[1:]


def get_docker(default=None, env=None):
    if env is None:
        env = os.environ

    return env.get(DOCKER, default)


def get_http_timeout(default=10, env=None):
    if env is None:
        env = os.environ

    return int(env.get(HTTP_TIMEOUT, default))


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


def get_username(default=None, env=None):
    if env is None:
        env = os.environ

    return env.get(USERNAME, default)


def get_user_email(default=None, env=None):
    if env is None:
        env = os.environ

    return env.get(USER_EMAIL, default)


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


def get_tags(default="", env=None):
    if env is None:
        env = os.environ

    return [tag for tag in env.get(TAGS, default).split(",") if tag]


def get_dir(default=None, env=None):
    if env is None:
        env = os.environ
    return env.get(DIR, default)


def get_config_paths():
    pass


def get_agent_report_interval(default=None, env=None):
    if env is None:
        env = os.environ
    val = env.get(AGENT_REPORT_INTERVAL, default)
    try:
        val = int(val)
    except ValueError:
        val = None  # silently ignore env format errors, caller should handle.
    return val


def get_agent_kill_delay(default=None, env=None):
    if env is None:
        env = os.environ
    val = env.get(AGENT_KILL_DELAY, default)
    try:
        val = int(val)
    except ValueError:
        val = None  # silently ignore env format errors, caller should handle.
    return val


def get_crash_nosync_time(default=None, env=None):
    if env is None:
        env = os.environ
    val = env.get(CRASH_NOSYNC_TIME, default)
    try:
        val = int(val)
    except ValueError:
        val = None  # silently ignore env format errors, caller should handle.
    return val


def get_magic(default=None, env=None):
    if env is None:
        env = os.environ
    val = env.get(MAGIC, default)
    return val


def set_entity(value, env=None):
    if env is None:
        env = os.environ
    env[ENTITY] = value


def set_project(value, env=None):
    if env is None:
        env = os.environ
    env[PROJECT] = value or "uncategorized"
