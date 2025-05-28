"""Decorators for W&B Table operations."""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable, TypeVar

from typing_extensions import Concatenate, ParamSpec

import wandb

_P = ParamSpec("_P")
_T = TypeVar("_T")


def allow_relogging_after_mutation(
    method: Callable[Concatenate[wandb.Table, _P], _T],
) -> Callable[Concatenate[wandb.Table, _P], _T]:
    """Decorator that handles table state after mutations based on log_mode.

    For MUTABLE tables, resets the run and artifact target to allow re-logging.
    For IMMUTABLE tables, warns if attempting to mutate after logging.
    """

    @wraps(method)
    def wrapper(self: wandb.Table, *args: Any, **kwargs: Any) -> _T:
        has_been_logged = self._run is not None or self._artifact_target is not None

        if self.log_mode == "MUTABLE":
            self._run = None
            self._artifact_target = None
            self._path = None
            self._sha256 = None
        elif self.log_mode == "IMMUTABLE" and has_been_logged:
            wandb.termwarn(
                "You are mutating a Table with log_mode='IMMUTABLE' that has been "
                "logged already. Subsequent log() calls will have no effect. "
                "Set log_mode='MUTABLE' to enable re-logging after mutations",
                repeat=False,
            )

        return method(self, *args, **kwargs)

    return wrapper


def allow_incremental_logging_after_append(
    method: Callable[Concatenate[wandb.Table, _P], _T],
) -> Callable[Concatenate[wandb.Table, _P], _T]:
    """Decorator that handles incremental logging state after append operations.

    For INCREMENTAL tables, manages artifact references and increments counters
    to support partial data logging.
    """

    @wraps(method)
    def wrapper(self: wandb.Table, *args: Any, **kwargs: Any) -> _T:
        res = method(self, *args, **kwargs)

        if self.log_mode != "INCREMENTAL" or self._artifact_target is None:
            return res

        art_entry_url = self._get_artifact_entry_ref_url()
        if art_entry_url is not None:
            if self._previous_increments_paths is None:
                raise ValueError(
                    "_previous_increments_paths must be set if incremental"
                    " table has been logged already"
                )
            self._previous_increments_paths.append(art_entry_url)
        self._run = None
        self._artifact_target = None
        self._path = None
        self._sha256 = None

        if self._increment_num is None:
            raise ValueError(
                "_increment_num must be set if incremental table has been"
                " logged already"
            )

        self._increment_num += 1
        if self._increment_num > 99:
            wandb.termwarn(
                "You have exceeded 100 increments for this table. "
                "Only the latest 100 increments will be visualized in the run workspace.",
                repeat=False,
            )
        return res

    return wrapper


def ensure_not_incremental(
    method: Callable[Concatenate[wandb.Table, _P], _T],
) -> Callable[Concatenate[wandb.Table, _P], _T]:
    """Decorator that checks if log mode is incremental to disallow methods from being called."""

    @wraps(method)
    def wrapper(self: wandb.Table, *args: Any, **kwargs: Any) -> _T:
        if self.log_mode == "INCREMENTAL":
            raise wandb.Error(
                f"Operation '{method.__name__}' is not supported for tables with "
                "log_mode='INCREMENTAL'. Use a different log mode like 'MUTABLE' or 'IMMUTABLE'."
            )
        return method(self, *args, **kwargs)

    return wrapper
