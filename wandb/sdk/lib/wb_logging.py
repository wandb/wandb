"""Logging configuration for the "wandb" logger.

Most log statements in wandb are made in the context of a run and should be
redirected to that run's log file (usually named 'debug.log'). This module
provides a context manager to temporarily set the current run ID and registers
a global handler for the 'wandb' logger that sends log statements to the right
place.

All functions in this module are threadsafe.

NOTE: The pytest caplog fixture will fail to capture logs from the wandb logger
because they are not propagated to the root logger.
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
import pathlib
from typing import Iterator


class _NotRunSpecific:
    """Sentinel for `not_run_specific()`."""


_NOT_RUN_SPECIFIC = _NotRunSpecific()


_run_id: contextvars.ContextVar[str | _NotRunSpecific | None] = contextvars.ContextVar(
    "_run_id",
    default=None,
)

_logger = logging.getLogger("wandb")


def configure_wandb_logger() -> None:
    """Configures the global 'wandb' logger.

    The wandb logger is not intended to be customized by users. Instead, it is
    used as a mechanism to redirect log messages into wandb run-specific log
    files.

    This function is idempotent: calling it multiple times has the same effect.
    """
    # Send all DEBUG and above messages to registered handlers.
    #
    # Per-run handlers can set different levels.
    _logger.setLevel(logging.DEBUG)

    # Do not propagate wandb logs to the root logger, which the user may have
    # configured to point elsewhere. All wandb log messages should go to a run's
    # log file.
    _logger.propagate = False

    # If no handlers are configured for the 'wandb' logger, don't activate the
    # "lastResort" handler which sends messages to stderr with a level of
    # WARNING by default.
    #
    # This occurs in wandb code that runs outside the context of a Run and
    # not as part of the CLI.
    #
    # Most such code uses the `termlog` / `termwarn` / `termerror` methods
    # to communicate with the user. When that code executes while a run is
    # active, its logger messages go to that run's log file.
    if not _logger.handlers:
        _logger.addHandler(logging.NullHandler())


@contextlib.contextmanager
def log_to_run(run_id: str | None) -> Iterator[None]:
    """Direct all wandb log messages to the given run.

    Args:
        id: The current run ID, or None if actions in the context manager are
            not associated to a specific run. In the latter case, log messages
            will go to all runs.

    Usage:

        with wb_logging.run_id(...):
            ... # Log messages here go to the specified run's logger.
    """
    token = _run_id.set(run_id)
    try:
        yield
    finally:
        _run_id.reset(token)


@contextlib.contextmanager
def log_to_all_runs() -> Iterator[None]:
    """Direct wandb log messages to all runs.

    Unlike `log_to_run(None)`, this indicates an intentional choice.
    This is often convenient to use as a decorator:

        @wb_logging.log_to_all_runs()
        def my_func():
            ... # Log messages here go to the specified run's logger.
    """
    token = _run_id.set(_NOT_RUN_SPECIFIC)
    try:
        yield
    finally:
        _run_id.reset(token)


def add_file_handler(run_id: str, filepath: pathlib.Path) -> logging.Handler:
    """Direct log messages for a run to a file.

    Args:
        run_id: The run for which to create a log file.
        filepath: The file to write log messages to.

    Returns:
        The added handler which can then be configured further or removed
        from the 'wandb' logger directly.

        The default logging level is INFO.
    """
    handler = logging.FileHandler(filepath)
    handler.setLevel(logging.INFO)
    handler.addFilter(_RunIDFilter(run_id))
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)-7s %(threadName)-10s:%(process)d"
            " [%(filename)s:%(funcName)s():%(lineno)s]%(run_id_tag)s"
            " %(message)s"
        )
    )

    _logger.addHandler(handler)
    return handler


class _RunIDFilter(logging.Filter):
    """Filters out messages logged for a different run."""

    def __init__(self, run_id: str) -> None:
        """Create a _RunIDFilter.

        Args:
            run_id: Allows messages when the run ID is this or None.
        """
        self._run_id = run_id

    def filter(self, record: logging.LogRecord) -> bool:
        run_id = _run_id.get()

        if run_id is None:
            record.run_id_tag = " [no run ID]"
            return True
        elif isinstance(run_id, _NotRunSpecific):
            record.run_id_tag = " [all runs]"
            return True
        else:
            record.run_id_tag = ""
            return run_id == self._run_id
