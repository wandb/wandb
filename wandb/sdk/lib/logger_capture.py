from __future__ import annotations

import logging

from typing_extensions import override

import wandb


class LoggerHandler(logging.Handler):
    """A logging.Handler that forwards log records using `run.write_logs()`."""

    def __init__(
        self,
        run: wandb.Run,
        level: int | str = logging.NOTSET,
    ) -> None:
        super().__init__(level=level)
        self._run = run
        self.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))

    @override
    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._run.write_logs(self.format(record))
        except Exception:
            self.handleError(record)
