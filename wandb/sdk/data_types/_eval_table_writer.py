from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol, get_args

if TYPE_CHECKING:
    from wandb.sdk.data_types.table import ColumnKey, LogMode
    from wandb.sdk.wandb_run import Run as LocalRun


UnsupportedMediaMode = Literal["stub", "raise"]
_UNSUPPORTED_MEDIA_MODES = get_args(UnsupportedMediaMode)


def validate_unsupported_media_mode(mode: str) -> None:
    if mode not in _UNSUPPORTED_MEDIA_MODES:
        raise ValueError(
            "unsupported_media_mode must be one of "
            f"{_UNSUPPORTED_MEDIA_MODES}, got {mode!r}."
        )


@dataclass(frozen=True, kw_only=True)
class EvalTableWriteRow:
    inputs: Mapping[str, Any]
    output: Mapping[str, Any] | None
    scores: Mapping[str, Any]


@dataclass(frozen=True, kw_only=True)
class EvalTableWriteInput:
    name: str
    rows: Sequence[EvalTableWriteRow]
    column_keys: Mapping[str, ColumnKey]
    ncols: int
    log_mode: LogMode


@dataclass(frozen=True, kw_only=True)
class EvalTableWriteResult:
    """Backend-owned run-history marker and its backend-specific identifier."""

    marker: Mapping[str, Any]
    logged_id: str


class EvalTableWriter(Protocol):
    """Backend client for writing an EvalTable.

    `validate_cell_value` may run before `bind` while Table constructs its rows.
    `bind` establishes the run context and precedes `write`. A successful write
    is cached, while a failed write may be retried. `logged_id` identifies the
    evaluation written by the selected backend.
    """

    def bind_to_run(self, run: LocalRun, key: str, step: int | str) -> None:
        """Bind this writer to a run."""
        ...

    def validate_cell_value(self, value: Any, column: ColumnKey) -> None: ...

    def write(self, payload: EvalTableWriteInput) -> EvalTableWriteResult: ...
