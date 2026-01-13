from __future__ import annotations

import time
from contextlib import AbstractContextManager
from typing import TYPE_CHECKING

from wandb.errors.term import termlog

if TYPE_CHECKING:
    from types import TracebackType

    from typing_extensions import Self


class TimedIf(AbstractContextManager):
    """Context manager that times a block of code only if a condition is satisfied."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.start: float | None = None

    def __enter__(self) -> Self:
        if self.enabled:
            self.start = time.monotonic()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        exc_traceback: TracebackType | None,
    ) -> None:
        if (start := self.start) is not None:
            termlog(f"Done. {time.monotonic() - start:.1f}s", prefix=False)
