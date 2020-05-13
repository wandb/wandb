"""Setup wandb session.

This module configures a wandb session which can extend to mutiple wandb runs.

Functions:
    setup(): Configure wandb session.

Early logging keeps track of logger output until the call to wandb.init() when the
run_id can be resolved.

"""

import copy
import logging
import multiprocessing
import os
import sys
import threading

import wandb

from . import wandb_settings

logger = (
    None  # will be configured to be either a standard logger instance or _EarlyLogger
)


def _set_logger(log_object):
    """Configure module logger."""
    global logger
    logger = log_object


class _EarlyLogger(object):
    """Early logger which captures logs in memory until logging can be configured."""

    def __init__(self):
        self._log = []
        self._exception = []

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

    def __init__(self, settings=None, environ=None):
        self._multiprocessing = None
        self._settings = None
        self._environ = environ or dict(os.environ)
        self._config = None

        # TODO(jhr): defer strict checks until settings are fully initialized
        #            and logging is ready
        self._early_logger = _EarlyLogger()
        _set_logger(self._early_logger)
        self._settings_setup(settings, self._early_logger)
        self._settings.freeze()

        self._check()
        self._setup()
        self._gitstuff()

    def _gitstuff(self):
        # self.git = GitRepo(remote=self.settings("git_remote"))
        # self.git = GitRepo()
        # print("remote", self.git.remote_url)
        # print("last", self.git.last_commit)
        pass

    def _settings_setup(self, settings=None, early_logger=None):
        s = wandb_settings.Settings(
            _environ=self._environ,
            _files=True,
            _early_logger=early_logger,
            _settings=settings,
        )
        # if settings:
        #     s.update(dict(settings))

        # setup defaults
        s.setdefaults()
        s._probe()

        # move freeze to later
        # TODO(jhr): is this ok?
        # s.freeze()
        self._settings = s

    def _early_logger_flush(self, new_logger):
        if not self._early_logger:
            return
        _set_logger(new_logger)
        self._settings._clear_early_logger()
        self._early_logger._flush()

    def _get_logger(self):
        return logger

    def settings(self, __d=None, **kwargs):
        s = copy.copy(self._settings)
        s.update(__d, **kwargs)
        return s

    def _check(self):
        if hasattr(threading, "main_thread"):
            if threading.current_thread() is not threading.main_thread():
                print("bad thread")
        elif threading.current_thread().name != "MainThread":
            print("bad thread2", threading.current_thread().name)
        if getattr(sys, "frozen", False):
            print("frozen, could be trouble")
        # print("t2", multiprocessing.get_start_method(allow_none=True))
        # print("t3", multiprocessing.get_start_method())

    def _setup(self):
        # TODO: use fork context if unix and frozen?
        # if py34+, else fall back
        if hasattr(multiprocessing, "get_context"):
            all_methods = multiprocessing.get_all_start_methods()
            logger.info(
                "multiprocessing start_methods={}".format(",".join(all_methods))
            )
            ctx = multiprocessing.get_context("spawn")
        else:
            logger.info("multiprocessing fallback, likely fork on unix")
            ctx = multiprocessing
        self._multiprocessing = ctx
        # print("t3b", self._multiprocessing.get_start_method())

        # if config_paths was set, read in config dict
        if self._settings.config_paths:
            # TODO(jhr): handle load errors, handle list of files
            self._config = wandb.wandb_sdk.Config._dict_from_config_file(
                self._settings.config_paths
            )

    def on_finish(self):
        logger.info("done")


class _WandbSetup(object):
    """Wandb singleton class."""

    _instance = None

    def __init__(self, settings=None):
        if _WandbSetup._instance is not None:
            logger.warning(
                "Ignoring settings passed to wandb.setup() "
                "which has already been configured."
            )
            return
        _WandbSetup._instance = _WandbSetup__WandbSetup(settings=settings)

    def __getattr__(self, name):
        return getattr(self._instance, name)


def setup(settings=None):
    """Setup library context."""
    wl = _WandbSetup(settings=settings)
    return wl
