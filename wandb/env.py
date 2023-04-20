#!/usr/bin/env python

"""All of W&B's environment variables

Getters and putters for all of them should go here. That
way it'll be easier to avoid typos with names and be
consistent about environment variables' semantics.

Environment variables are not the authoritative source for
these values in many cases.
"""

import json
import os
import sys
from distutils.util import strtobool
from typing import List, MutableMapping, Optional, Union

import appdirs

Env = Optional[MutableMapping]

CONFIG_PATHS = "WANDB_CONFIG_PATHS"
SWEEP_PARAM_PATH = "WANDB_SWEEP_PARAM_PATH"
SHOW_RUN = "WANDB_SHOW_RUN"
DEBUG = "WANDB_DEBUG"
SILENT = "WANDB_SILENT"
QUIET = "WANDB_QUIET"
INITED = "WANDB_INITED"
DIR = "WANDB_DIR"
# Deprecate DESCRIPTION in a future release
DESCRIPTION = "WANDB_DESCRIPTION"
NAME = "WANDB_NAME"
NOTEBOOK_NAME = "WANDB_NOTEBOOK_NAME"
NOTES = "WANDB_NOTES"
USERNAME = "WANDB_USERNAME"
USER_EMAIL = "WANDB_USER_EMAIL"
PROJECT = "WANDB_PROJECT"
ENTITY = "WANDB_ENTITY"
BASE_URL = "WANDB_BASE_URL"
APP_URL = "WANDB_APP_URL"
PROGRAM = "WANDB_PROGRAM"
ARGS = "WANDB_ARGS"
MODE = "WANDB_MODE"
START_METHOD = "WANDB_START_METHOD"
RESUME = "WANDB_RESUME"
RUN_ID = "WANDB_RUN_ID"
RUN_STORAGE_ID = "WANDB_RUN_STORAGE_ID"
RUN_GROUP = "WANDB_RUN_GROUP"
RUN_DIR = "WANDB_RUN_DIR"
SWEEP_ID = "WANDB_SWEEP_ID"
HTTP_TIMEOUT = "WANDB_HTTP_TIMEOUT"
API_KEY = "WANDB_API_KEY"
JOB_TYPE = "WANDB_JOB_TYPE"
DISABLE_CODE = "WANDB_DISABLE_CODE"
DISABLE_GIT = "WANDB_DISABLE_GIT"
GIT_ROOT = "WANDB_GIT_ROOT"
SAVE_CODE = "WANDB_SAVE_CODE"
TAGS = "WANDB_TAGS"
IGNORE = "WANDB_IGNORE_GLOBS"
ERROR_REPORTING = "WANDB_ERROR_REPORTING"
DOCKER = "WANDB_DOCKER"
AGENT_REPORT_INTERVAL = "WANDB_AGENT_REPORT_INTERVAL"
AGENT_KILL_DELAY = "WANDB_AGENT_KILL_DELAY"
AGENT_DISABLE_FLAPPING = "WANDB_AGENT_DISABLE_FLAPPING"
AGENT_MAX_INITIAL_FAILURES = "WANDB_AGENT_MAX_INITIAL_FAILURES"
CRASH_NOSYNC_TIME = "WANDB_CRASH_NOSYNC_TIME"
MAGIC = "WANDB_MAGIC"
HOST = "WANDB_HOST"
ANONYMOUS = "WANDB_ANONYMOUS"
JUPYTER = "WANDB_JUPYTER"
CONFIG_DIR = "WANDB_CONFIG_DIR"
DATA_DIR = "WANDB_DATA_DIR"
ARTIFACT_DIR = "WANDB_ARTIFACT_DIR"
CACHE_DIR = "WANDB_CACHE_DIR"
DISABLE_SSL = "WANDB_INSECURE_DISABLE_SSL"
SERVICE = "WANDB_SERVICE"
_DISABLE_SERVICE = "WANDB_DISABLE_SERVICE"
SENTRY_DSN = "WANDB_SENTRY_DSN"
INIT_TIMEOUT = "WANDB_INIT_TIMEOUT"
GIT_COMMIT = "WANDB_GIT_COMMIT"
GIT_REMOTE_URL = "WANDB_GIT_REMOTE_URL"
_EXECUTABLE = "WANDB_EXECUTABLE"

# For testing, to be removed in future version
USE_V1_ARTIFACTS = "_WANDB_USE_V1_ARTIFACTS"


def immutable_keys() -> List[str]:
    """These are env keys that shouldn't change within a single process.  We use this to maintain
    certain values between multiple calls to wandb.init within a single process."""
    return [
        DIR,
        ENTITY,
        PROJECT,
        API_KEY,
        IGNORE,
        DISABLE_CODE,
        DISABLE_GIT,
        DOCKER,
        MODE,
        BASE_URL,
        ERROR_REPORTING,
        CRASH_NOSYNC_TIME,
        MAGIC,
        USERNAME,
        USER_EMAIL,
        DIR,
        SILENT,
        CONFIG_PATHS,
        ANONYMOUS,
        RUN_GROUP,
        JOB_TYPE,
        TAGS,
        RESUME,
        AGENT_REPORT_INTERVAL,
        HTTP_TIMEOUT,
        HOST,
        DATA_DIR,
        ARTIFACT_DIR,
        CACHE_DIR,
        USE_V1_ARTIFACTS,
        DISABLE_SSL,
    ]


def _env_as_bool(
    var: str, default: Optional[str] = None, env: Optional[Env] = None
) -> bool:
    if env is None:
        env = os.environ
    val = env.get(var, default)
    try:
        val = bool(strtobool(val))  # type: ignore
    except (AttributeError, ValueError):
        pass
    return val if isinstance(val, bool) else False


def is_debug(default: Optional[str] = None, env: Optional[Env] = None) -> bool:
    return _env_as_bool(DEBUG, default=default, env=env)


def error_reporting_enabled() -> bool:
    return _env_as_bool(ERROR_REPORTING, default="True")


def ssl_disabled() -> bool:
    return _env_as_bool(DISABLE_SSL, default="False")


def get_error_reporting(
    default: Union[bool, str] = True,
    env: Optional[Env] = None,
) -> Union[bool, str]:
    if env is None:
        env = os.environ

    return env.get(ERROR_REPORTING, default)


def get_run(default: Optional[str] = None, env: Optional[Env] = None) -> Optional[str]:
    if env is None:
        env = os.environ

    return env.get(RUN_ID, default)


def get_args(
    default: Optional[List[str]] = None, env: Optional[Env] = None
) -> Optional[List[str]]:
    if env is None:
        env = os.environ
    if env.get(ARGS):
        try:
            return json.loads(env.get(ARGS, "[]"))  # type: ignore
        except ValueError:
            return None
    else:
        return default or sys.argv[1:]


def get_docker(
    default: Optional[str] = None, env: Optional[Env] = None
) -> Optional[str]:
    if env is None:
        env = os.environ

    return env.get(DOCKER, default)


def get_http_timeout(default: int = 10, env: Optional[Env] = None) -> int:
    if env is None:
        env = os.environ

    return int(env.get(HTTP_TIMEOUT, default))


def get_ignore(
    default: Optional[List[str]] = None, env: Optional[Env] = None
) -> Optional[List[str]]:
    if env is None:
        env = os.environ
    ignore = env.get(IGNORE)
    if ignore is not None:
        return ignore.split(",")
    else:
        return default


def get_project(
    default: Optional[str] = None, env: Optional[Env] = None
) -> Optional[str]:
    if env is None:
        env = os.environ

    return env.get(PROJECT, default)


def get_username(
    default: Optional[str] = None, env: Optional[Env] = None
) -> Optional[str]:
    if env is None:
        env = os.environ

    return env.get(USERNAME, default)


def get_user_email(
    default: Optional[str] = None, env: Optional[Env] = None
) -> Optional[str]:
    if env is None:
        env = os.environ

    return env.get(USER_EMAIL, default)


def get_entity(
    default: Optional[str] = None, env: Optional[Env] = None
) -> Optional[str]:
    if env is None:
        env = os.environ

    return env.get(ENTITY, default)


def get_base_url(
    default: Optional[str] = None, env: Optional[Env] = None
) -> Optional[str]:
    if env is None:
        env = os.environ

    base_url = env.get(BASE_URL, default)

    return base_url.rstrip("/") if base_url is not None else base_url


def get_app_url(
    default: Optional[str] = None, env: Optional[Env] = None
) -> Optional[str]:
    if env is None:
        env = os.environ

    return env.get(APP_URL, default)


def get_show_run(default: Optional[str] = None, env: Optional[Env] = None) -> bool:
    if env is None:
        env = os.environ

    return bool(env.get(SHOW_RUN, default))


def get_description(
    default: Optional[str] = None, env: Optional[Env] = None
) -> Optional[str]:
    if env is None:
        env = os.environ

    return env.get(DESCRIPTION, default)


def get_tags(default: str = "", env: Optional[Env] = None) -> List[str]:
    if env is None:
        env = os.environ

    return [tag for tag in env.get(TAGS, default).split(",") if tag]


def get_dir(default: Optional[str] = None, env: Optional[Env] = None) -> Optional[str]:
    if env is None:
        env = os.environ
    return env.get(DIR, default)


def get_config_paths(
    default: Optional[str] = None, env: Optional[Env] = None
) -> Optional[str]:
    if env is None:
        env = os.environ
    return env.get(CONFIG_PATHS, default)


def get_agent_report_interval(
    default: Optional[str] = None, env: Optional[Env] = None
) -> Optional[int]:
    if env is None:
        env = os.environ
    val = env.get(AGENT_REPORT_INTERVAL, default)
    try:
        val = int(val)  # type: ignore
    except ValueError:
        val = None  # silently ignore env format errors, caller should handle.
    return val


def get_agent_kill_delay(
    default: Optional[str] = None, env: Optional[Env] = None
) -> Optional[int]:
    if env is None:
        env = os.environ
    val = env.get(AGENT_KILL_DELAY, default)
    try:
        val = int(val)  # type: ignore
    except ValueError:
        val = None  # silently ignore env format errors, caller should handle.
    return val


def get_crash_nosync_time(
    default: Optional[str] = None, env: Optional[Env] = None
) -> Optional[int]:
    if env is None:
        env = os.environ
    val = env.get(CRASH_NOSYNC_TIME, default)
    try:
        val = int(val)  # type: ignore
    except ValueError:
        val = None  # silently ignore env format errors, caller should handle.
    return val


def get_magic(
    default: Optional[str] = None, env: Optional[Env] = None
) -> Optional[str]:
    if env is None:
        env = os.environ
    val = env.get(MAGIC, default)
    return val


def get_data_dir(env: Optional[Env] = None) -> str:
    default_dir = appdirs.user_data_dir("wandb")
    if env is None:
        env = os.environ
    val = env.get(DATA_DIR, default_dir)
    return val


def get_artifact_dir(env: Optional[Env] = None) -> str:
    default_dir = os.path.join(".", "artifacts")
    if env is None:
        env = os.environ
    val = env.get(ARTIFACT_DIR, default_dir)
    return val


def get_cache_dir(env: Optional[Env] = None) -> str:
    default_dir = appdirs.user_cache_dir("wandb")
    if env is None:
        env = os.environ
    val = env.get(CACHE_DIR, default_dir)
    return val


def get_use_v1_artifacts(env: Optional[Env] = None) -> bool:
    if env is None:
        env = os.environ
    val = bool(env.get(USE_V1_ARTIFACTS, False))
    return val


def get_agent_max_initial_failures(
    default: Optional[int] = None, env: Optional[Env] = None
) -> Optional[int]:
    if env is None:
        env = os.environ
    val = env.get(AGENT_MAX_INITIAL_FAILURES, default)
    try:
        val = int(val)  # type: ignore
    except ValueError:
        val = default
    return val


def set_entity(value: str, env: Optional[Env] = None) -> None:
    if env is None:
        env = os.environ
    env[ENTITY] = value


def set_project(value: str, env: Optional[Env] = None) -> None:
    if env is None:
        env = os.environ
    env[PROJECT] = value or "uncategorized"


def should_save_code() -> bool:
    save_code = _env_as_bool(SAVE_CODE, default="False")
    code_disabled = _env_as_bool(DISABLE_CODE, default="False")
    return save_code and not code_disabled


def disable_git(env: Optional[Env] = None) -> bool:
    if env is None:
        env = os.environ
    val = env.get(DISABLE_GIT, default="False")
    if isinstance(val, str):
        val = False if val.lower() == "false" else True
    return val
