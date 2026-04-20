"""A logging integration for convenience: routes Python logger output to W&B Logs tab."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wandb.sdk.wandb_run import Run


class WandbLoggerHandler(logging.Handler):
    """A logging.Handler that sends formatted log records to the W&B Logs tab.

    Provided as a convenience integration for Python's logging module.
    Users who want full control can call ``run.write_logs()`` directly instead.

    Example::

        import logging
        import wandb

        with wandb.init() as run:
            handler = WandbLoggerHandler(run)
            handler.setLevel(logging.INFO)
            logging.getLogger("my_app").addHandler(handler)
    """

    def __init__(self, run: Run, level: int = logging.NOTSET) -> None:
        super().__init__(level=level)
        self._run = run

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._run.write_logs(self.format(record))
        except Exception:
            self.handleError(record)
