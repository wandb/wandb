# -*- coding: utf-8 -*-
"""
module earlylogger
"""

import logging

import wandb


if wandb.TYPE_CHECKING:  # type: ignore
    from typing import (  # noqa: F401 pylint: disable=unused-import
        Dict,
        List,
        Optional,
        Union,
        Tuple,
        Callable,
        Set,
        Type,
        Sequence,
    )
    from logging import Logger
    from typing import NewType

    EarlyLoggerType = NewType("EarlyLoggerType", Logger)


class EarlyLogger(object):
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

    def _flush(self, logger):
        assert self is not logger
        for level, msg, args, kwargs in self._log:
            logger.log(level, msg, *args, **kwargs)
        for msg, args, kwargs in self._exception:
            logger.exception(msg, *args, **kwargs)
