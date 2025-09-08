from __future__ import annotations

from contextvars import ContextVar
from functools import wraps
from typing import Callable, Final, TypeVar
from uuid import UUID, uuid4

from pydantic.dataclasses import dataclass as pydantic_dataclass
from typing_extensions import ParamSpec

from wandb._strutils import nameof

P = ParamSpec("P")
R = TypeVar("R")


@pydantic_dataclass(frozen=True, slots=True)
class TrackedFuncInfo:
    id_: UUID  #: A unique identifier individual to each call to the tracked function.
    name: str  #: The fully qualified namespace of the tracked function.

    def to_headers(self) -> dict[str, str]:
        return {
            X_WANDB_PYTHON_CALL_ID: str(self.id_),
            X_WANDB_PYTHON_FUNC: self.name,
        }


_current_func: ContextVar[TrackedFuncInfo] = ContextVar("_current_func")


# Header keys for tracking the calling function
X_WANDB_PYTHON_FUNC: Final[str] = "X-Wandb-Python-Func"
X_WANDB_PYTHON_CALL_ID: Final[str] = "X-Wandb-Python-Call-Id"


def tracked(func: Callable[P, R]) -> Callable[P, R]:
    """A decorator to inject the calling function name into any GraphQL request headers.

    If a tracked function calls another tracked function, only the outermost function in
    the call stack will be tracked.
    """
    func_namespace = f"{func.__module__}.{nameof(func)}"

    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        # Don't override the current tracked function if it's already set
        if tracked_func() is not None:
            return func(*args, **kwargs)

        token = _current_func.set(TrackedFuncInfo(id_=uuid4(), name=func_namespace))
        try:
            return func(*args, **kwargs)
        finally:
            _current_func.reset(token)

    return wrapper


def tracked_func() -> str | None:
    """Returns the fully qualified namespace of the current tracked function."""
    return _current_func.get(None)
