"""Capture output from named Python loggers into wandb console output."""

from __future__ import annotations

import logging
from typing import Callable


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
