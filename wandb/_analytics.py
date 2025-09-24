from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
from typing import Callable, Final, TypeVar
from uuid import UUID, uuid4

from typing_extensions import ParamSpec

from wandb._strutils import nameof

P = ParamSpec("P")
R = TypeVar("R")

# Header keys for tracking the calling function
X_WANDB_PYTHON_FUNC: Final[str] = "X-Wandb-Python-Func"
X_WANDB_PYTHON_CALL_ID: Final[str] = "X-Wandb-Python-Call-Id"


@dataclass(frozen=True)
class TrackedFuncInfo:
    func: str
    """The fully qualified namespace of the tracked function."""

    call_id: UUID = field(default_factory=uuid4)
    """A unique identifier assigned to each invocation."""

    def to_headers(self) -> dict[str, str]:
        return {
            X_WANDB_PYTHON_FUNC: self.func,
            X_WANDB_PYTHON_CALL_ID: str(self.call_id),
        }


_current_func: ContextVar[TrackedFuncInfo] = ContextVar("_current_func")
"""An internal, threadsafe context variable to hold the current function being tracked."""


def tracked(func: Callable[P, R]) -> Callable[P, R]:
    """A decorator to inject the calling function name into any GraphQL request headers.

    If a tracked function calls another tracked function, only the outermost function in
    the call stack will be tracked.
    """
    func_namespace = f"{func.__module__}.{nameof(func)}"

    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        # Don't override the current tracked function if it's already set
        if tracked_func():
            return func(*args, **kwargs)

        token = _current_func.set(TrackedFuncInfo(func=func_namespace))
        try:
            return func(*args, **kwargs)
        finally:
            _current_func.reset(token)

    return wrapper


def tracked_func() -> TrackedFuncInfo | None:
    """Returns info on the current tracked function, if any, otherwise None."""
    return _current_func.get(None)
