"""The state of a sweep run, shared by the schedulers that drive sweeps."""

from __future__ import annotations

from enum import Enum
from typing import Any

__all__ = ["RunState"]


class RunState(Enum):
    """A sweep run's state, paired with whether that state is alive or dead."""

    RUNNING = "running", "alive"
    PENDING = "pending", "alive"
    PREEMPTING = "preempting", "alive"
    CRASHED = "crashed", "dead"
    FAILED = "failed", "dead"
    KILLED = "killed", "dead"
    FINISHED = "finished", "dead"
    PREEMPTED = "preempted", "dead"
    # unknown when api.get_run_state fails or returns an unexpected state.
    # Classified alive; the launch scheduler moves a run to FAILED (dead)
    # itself after two consecutive unknown polls.
    UNKNOWN = "unknown", "alive"

    def __new__(cls: Any, *args: list, **kwds: Any) -> RunState:
        """Use only the first tuple element as the member's value."""
        obj: RunState = object.__new__(cls)
        obj._value_ = args[0]
        return obj

    def __init__(self, value: str, life: str = "unknown") -> None:
        """Store the life classification; `value` is consumed by `__new__`."""
        self._life = life

    @property
    def is_alive(self) -> bool:
        """True while a run in this state may still make progress."""
        return self._life == "alive"
