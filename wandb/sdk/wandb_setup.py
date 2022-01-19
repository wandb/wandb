#
"""Setup wandb session.

This module configures a wandb session which can extend to mutiple wandb runs.

Functions:
    setup(): Configure wandb session.

Early logging keeps track of logger output until the call to wandb.init() when the
run_id can be resolved.

"""

import copy
import logging
import os
import sys
import threading
from typing import Optional

import wandb

from . import wandb_manager
from . import wandb_settings
from .lib import config_util, debug_log, server


# logger will be configured to be either a standard logger instance or _EarlyLogger
logger = None


def _set_logger(log_object):
    """Configure module logger."""
    global logger
    logger = log_object


class _EarlyLogger(object):
    """Early logger which captures logs in memory until logging can be configured."""

    def __init__(self):
        self._log = []
        self._exception = []
        # support old warn() as alias of warning()
        self.warn = self.warning

    def debug(self, msg, *args, **kwargs):
        self._log.append((logging.DEBUG, msg, args, kwargs))

    def info(self, msg, *args, **kwargs):
        self._log.append((logging.INFO, msg, args, kwargs))

    def warning(self, msg, *args, **kwargs):
        self._log.append((logging.WARNING, msg, args, kwargs))

    def error(self, msg, *args, **kwargs):
        self._log.append((logging.ERROR, msg, args, kwargs))

    def critical(self, msg, *args, **kwargs):
        self._log.append((logging.CRITICAL, msg, args, kwargs))

    def exception(self, msg, *args, **kwargs):
        self._exception.append(msg, args, kwargs)

    def log(self, level, msg, *args, **kwargs):
        self._log.append(level, msg, args, kwargs)

    def _flush(self):
        assert self is not logger
        for level, msg, args, kwargs in self._log:
            logger.log(level, msg, *args, **kwargs)
        for msg, args, kwargs in self._exception:
            logger.exception(msg, *args, **kwargs)


class _WandbSetup__WandbSetup(object):  # noqa: N801
    """Inner class of _WandbSetup."""

    _manager: Optional[wandb_manager._Manager]

    def __init__(self, settings=None, environ=None, pid=None):
        self._settings = None
        self._environ = environ or dict(os.environ)
        self._sweep_config = None
        self._config = None
        self._server = None
        self._manager = None
        self._pid = pid

        # keep track of multiple runs so we can unwind with join()s
        self._global_run_stack = []

        # TODO(jhr): defer strict checks until settings are fully initialized
        #            and logging is ready
        self._early_logger = _EarlyLogger()
        _set_logger(self._early_logger)

        self._settings_setup(settings, self._early_logger)
        self._settings.freeze()

        wandb.termsetup(self._settings, logger)

        self._check()
        self._setup()

        debug_log_mode = self._settings._debug_log
        if debug_log_mode:
            debug_log.enable(debug_log_mode)

    def _settings_setup(self, settings=None, early_logger=None):
        # TODO: Do a more formal merge of user settings from the backend.
        s = wandb_settings.Settings()
        s._apply_configfiles(_logger=early_logger)
        s._apply_environ(self._environ, _logger=early_logger)

        # NOTE: Do not update user settings until wandb.init() time
        # if not s._offline:
        #    user_settings = self._load_user_settings(settings=settings)
        #    s._apply_user(user_settings, _logger=early_logger)

        if settings:
            s._apply_settings(settings, _logger=early_logger)

        # setup defaults
        s.setdefaults()
        s._infer_settings_from_env()
        if not s._cli_only_mode:
            s._infer_run_settings_from_env(_logger=early_logger)

        # move freeze to later
        # TODO(jhr): is this ok?
        # s.freeze()
        self._settings = s

    def _update(self, settings=None):
        if settings:
            s = self._clone_settings()
            s._apply_settings(settings=settings)
            self._settings = s.freeze()

    def _update_user_settings(self, settings=None):
        settings = settings or self._settings
        s = self._clone_settings()
        # Get rid of cached results to force a refresh.
        self._server = None
        user_settings = self._load_user_settings(settings=settings)
        s._apply_user(user_settings)
        self._settings = s.freeze()

    def _early_logger_flush(self, new_logger):
        if not self._early_logger:
            return
        _set_logger(new_logger)
        # self._settings._clear_early_logger()
        self._early_logger._flush()

    def _get_logger(self):
        return logger

    @property
    def settings(self):
        return self._settings

    def _clone_settings(self, __d=None, **kwargs):
        s = copy.copy(self._settings)
        s.update(__d, **kwargs)
        return s

    def _get_entity(self):
        if self._settings and self._settings._offline:
            return None
        if self._server is None:
            self._load_viewer()
        entity = self._server._viewer.get("entity")
        return entity

    def _load_viewer(self, settings=None):
        if self._settings and self._settings._offline:
            return
        s = server.Server(settings=settings)
        s.query_with_timeout()
        self._server = s

    def _load_user_settings(self, settings=None):
        if self._server is None:
            self._load_viewer()

        flags = self._server._flags
        user_settings = {}
        if "code_saving_enabled" in flags:
            user_settings["save_code"] = flags["code_saving_enabled"]

        email = self._server._viewer.get("email", None)
        if email:
            user_settings["email"] = email

        return user_settings

    def _check(self):
        if hasattr(threading, "main_thread"):
            if threading.current_thread() is not threading.main_thread():
                pass
                # print("bad thread")
        elif threading.current_thread().name != "MainThread":
            print("bad thread2", threading.current_thread().name)
        if getattr(sys, "frozen", False):
            print("frozen, could be trouble")
        # print("t2", multiprocessing.get_start_method(allow_none=True))
        # print("t3", multiprocessing.get_start_method())

    def _setup(self):
        self._setup_manager()

        sweep_path = self._settings.sweep_param_path
        if sweep_path:
            self._sweep_config = config_util.dict_from_config_file(
                sweep_path, must_exist=True
            )

        # if config_paths was set, read in config dict
        if self._settings.config_paths:
            # TODO(jhr): handle load errors, handle list of files
            config_paths = self._settings.config_paths.split(",")
            for config_path in config_paths:
                config_dict = config_util.dict_from_config_file(config_path)
                if config_dict is None:
                    continue
                if self._config is not None:
                    self._config.update(config_dict)
                else:
                    self._config = config_dict

    def _teardown(self, exit_code: int = None):
        exit_code = exit_code or 0
        self._teardown_manager(exit_code=exit_code)

    def _setup_manager(self) -> None:
        if not self._settings._require_service:
            return
        # Temporary setting to allow use of grpc so that we can keep
        # that code from rotting during the transition
        use_grpc = self._settings._service_transport == "grpc"
        self._manager = wandb_manager._Manager(_use_grpc=use_grpc)

    def _teardown_manager(self, exit_code: int) -> None:
        if not self._manager:
            return
        self._manager._teardown(exit_code)
        self._manager = None

    def _get_manager(self) -> Optional[wandb_manager._Manager]:
        return self._manager


class _WandbSetup(object):
    """Wandb singleton class.

    Note: This is a process local singleton.
    (Forked processes will get a new copy of the object)
    """

    _instance = None

    def __init__(self, settings=None):
        pid = os.getpid()
        if _WandbSetup._instance and _WandbSetup._instance._pid == pid:
            _WandbSetup._instance._update(settings=settings)
            return
        _WandbSetup._instance = _WandbSetup__WandbSetup(settings=settings, pid=pid)

    def __getattr__(self, name):
        return getattr(self._instance, name)


def _setup(settings=None, _reset=None):
    """Setup library context."""
    if _reset:
        setup_instance = _WandbSetup._instance
        if setup_instance:
            setup_instance._teardown()
        _WandbSetup._instance = None
        return
    wl = _WandbSetup(settings=settings)
    return wl


def setup(settings=None):
    ret = _setup(settings=settings)
    return ret


def teardown(exit_code=None):
    setup_instance = _WandbSetup._instance
    if setup_instance:
        setup_instance._teardown(exit_code=exit_code)
    _WandbSetup._instance = None
