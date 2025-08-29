from __future__ import annotations

from contextvars import ContextVar
from functools import wraps
from typing import Callable, TypeVar

from typing_extensions import ParamSpec

P = ParamSpec("P")
R = TypeVar("R")


_current_func: ContextVar[str] = ContextVar("_current_func")

X_WANDB_PYTHON_FUNC = "X-Wandb-Python-Func"


def tracked(func: Callable[P, R]) -> Callable[P, R]:
    """A decorator to inject the calling function name into any GraphQL request headers.

    If a tracked function calls another tracked function, only the outermost function in
    the call stack will be tracked.
    """
    func_ns = f"{func.__module__}.{func.__qualname__}"

    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        # Don't override the current tracked function if it's already set
        if tracked_func() is not None:
            return func(*args, **kwargs)

        token = _current_func.set(func_ns)
        try:
            return func(*args, **kwargs)
        finally:
            _current_func.reset(token)

    return wrapper


def tracked_func() -> str | None:
    """Returns the fully qualified namespace of the current tracked function."""
    return _current_func.get(None)
