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
    func_ns = f"{func.__module__}.{func.__qualname__}"

    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        # Don't override the current tracked function if it's already set
        token = None if current_tracked_func() else _current_func.set(func_ns)

        try:
            return func(*args, **kwargs)
        finally:
            if token is not None:
                _current_func.reset(token)

    return wrapper


def current_tracked_func() -> str | None:
    return _current_func.get(None)
