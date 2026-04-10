"""Capture output from named Python loggers into wandb console output."""

from __future__ import annotations

import logging
from typing import Callable

_logger = logging.getLogger(__name__)


class WandbLoggerHandler(logging.Handler):
    """A logging.Handler that feeds log records into wandb's output pipeline.

    Each log record is formatted and published via the provided callback,
    which matches the signature of Run._console_callback(name, data).
    """

    def __init__(
        self,
        callback: Callable[[str, str], None],
        level: int = logging.INFO,
    ) -> None:
        super().__init__(level=level)
        self._callback = callback
        self.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            if not msg.endswith("\n"):
                msg += "\n"
            self._callback("stdout", msg)
        except Exception:
            self.handleError(record)


def install(
    loggers_config: dict[str, str],
    callback: Callable[[str, str], None],
) -> list[tuple[logging.Logger, WandbLoggerHandler]]:
    """Install WandbLoggerHandlers on the specified loggers.

    Args:
        loggers_config: Mapping of logger name to log level string.
        callback: The function to call with (stream_name, data).

    Returns:
        List of (logger, handler) pairs for later cleanup.
    """
    installed: list[tuple[logging.Logger, WandbLoggerHandler]] = []
    for logger_name, level_str in loggers_config.items():
        level = getattr(logging, level_str)
        target_logger = logging.getLogger(logger_name)
        handler = WandbLoggerHandler(callback=callback, level=level)
        target_logger.addHandler(handler)
        installed.append((target_logger, handler))

    _logger.info(
        "Installed logger capture on %d loggers: %s",
        len(installed),
        list(loggers_config.keys()),
    )
    return installed


def uninstall(
    handlers: list[tuple[logging.Logger, WandbLoggerHandler]],
) -> None:
    """Remove WandbLoggerHandlers installed by install().

    Args:
        handlers: The list returned by install().
    """
    for target_logger, handler in handlers:
        target_logger.removeHandler(handler)
        handler.close()
    _logger.info("Removed logger capture handlers.")
