#
"""Setup wandb session.

This module configures a wandb session which can extend to mutiple wandb runs.

Functions:
    setup(): Configure wandb session.

Early logging keeps track of logger output until the call to wandb.init() when the
run_id can be resolved.

"""

import logging
import os
import sys
import threading
from typing import (
    Any,
    Dict,
    Optional,
    Union,
)

import wandb

from . import wandb_manager
from . import wandb_settings
from .lib import config_util, server, tracelog


# logger will be configured to be either a standard logger instance or _EarlyLogger
logger = None


def _set_logger(log_object):
    """Configure module logger."""
    global logger
    logger = log_object


class _EarlyLogger:
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


class _WandbSetup__WandbSetup:  # noqa: N801
    """Inner class of _WandbSetup."""

    _manager: Optional[wandb_manager._Manager]

    def __init__(
        self,
        settings: Union["wandb_settings.Settings", Dict[str, Any], None] = None,
        environ: Optional[Dict[str, Any]] = None,
        pid: Optional[int] = None,
    ):
        self._environ = environ or dict(os.environ)
        self._sweep_config = None
        self._config = None
        self._server = None
        self._manager = None
        self._pid = pid

        # keep track of multiple runs, so we can unwind with join()s
        self._global_run_stack = []

        # TODO(jhr): defer strict checks until settings are fully initialized
        #            and logging is ready
        self._early_logger = _EarlyLogger()
        _set_logger(self._early_logger)

        self._settings = self._settings_setup(settings, self._early_logger)
        # self._settings.freeze()

        wandb.termsetup(self._settings, logger)

        self._check()
        self._setup()

        tracelog_mode = self._settings._tracelog
        if tracelog_mode:
            tracelog.enable(tracelog_mode)

    def _settings_setup(
        self,
        settings: Union["wandb_settings.Settings", Dict[str, Any], None] = None,
        early_logger: Optional[_EarlyLogger] = None,
    ):
        s = wandb_settings.Settings()
        s._apply_config_files(_logger=early_logger)
        s._apply_env_vars(self._environ, _logger=early_logger)

        if isinstance(settings, wandb_settings.Settings):
            s._apply_settings(settings, _logger=early_logger)
        elif isinstance(settings, dict):
            # if passed settings arg is a mapping, update the settings with it
            s._apply_setup(settings, _logger=early_logger)

        s._infer_settings_from_environment()
        if not s._cli_only_mode:
            s._infer_run_settings_from_environment(_logger=early_logger)

        return s

    def _update(
        self, settings: Union["wandb_settings.Settings", Dict[str, Any], None] = None
    ) -> None:
        if settings is None:
            return
        # self._settings.unfreeze()
        if isinstance(settings, wandb_settings.Settings):
            # todo: check the logic here. this _only_ comes up in tests?
            self._settings._apply_settings(settings)
        elif isinstance(settings, dict):
            # if it is a mapping, update the settings with it
            self._settings.update(settings, source=wandb_settings.Source.SETUP)
        # self._settings.freeze()

    def _update_user_settings(self, settings=None):
        settings = settings or self._settings
        # Get rid of cached results to force a refresh.
        self._server = None
        user_settings = self._load_user_settings(settings=settings)
        if user_settings is not None:
            # self._settings.unfreeze()
            self._settings._apply_user(user_settings)
            # self._settings.freeze()

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

    def _get_entity(self) -> Optional[str]:
        if self._settings and self._settings._offline:
            return None
        if self._server is None:
            self._load_viewer()
        entity = self._server._viewer.get("entity")
        return entity

    def _load_viewer(self, settings=None) -> None:
        if self._settings and self._settings._offline:
            return
        s = server.Server(settings=settings)
        s.query_with_timeout()
        self._server = s

    def _load_user_settings(self, settings=None) -> Optional[Dict[str, Any]]:
        if self._server is None:
            self._load_viewer(settings=settings)

        # offline?
        if self._server is None:
            return None

        flags = self._server._flags
        user_settings = dict()
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
        elif threading.current_thread().name != "MainThread":
            print("bad thread2", threading.current_thread().name)
        if getattr(sys, "frozen", False):
            print("frozen, could be trouble")

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
        self._manager = wandb_manager._Manager(
            _use_grpc=use_grpc, settings=self._settings
        )

    def _teardown_manager(self, exit_code: int) -> None:
        if not self._manager:
            return
        self._manager._teardown(exit_code)
        self._manager = None

    def _get_manager(self) -> Optional[wandb_manager._Manager]:
        return self._manager


class _WandbSetup:
    """Wandb singleton class.

    Note: This is a process local singleton.
    (Forked processes will get a new copy of the object)
    """

    _instance = None

    def __init__(self, settings=None) -> None:
        pid = os.getpid()
        if _WandbSetup._instance and _WandbSetup._instance._pid == pid:
            _WandbSetup._instance._update(settings=settings)
            return
        _WandbSetup._instance = _WandbSetup__WandbSetup(settings=settings, pid=pid)

    def __getattr__(self, name):
        return getattr(self._instance, name)


def _setup(settings=None, _reset: bool = False) -> Optional["_WandbSetup"]:
    """Setup library context."""
    if _reset:
        setup_instance = _WandbSetup._instance
        if setup_instance:
            setup_instance._teardown()
        _WandbSetup._instance = None
        return
    wl = _WandbSetup(settings=settings)
    return wl


def setup(settings=None) -> Optional["_WandbSetup"]:
    ret = _setup(settings=settings)
    return ret


def teardown(exit_code=None):
    setup_instance = _WandbSetup._instance
    if setup_instance:
        setup_instance._teardown(exit_code=exit_code)
    _WandbSetup._instance = None
