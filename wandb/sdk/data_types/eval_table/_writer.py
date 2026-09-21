from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from wandb.sdk.data_types.table import ColumnKey, LogMode
    from wandb.sdk.wandb_run import Run as LocalRun


@dataclass(frozen=True, kw_only=True)
class WriteRow:
    inputs: Mapping[str, Any]
    output: Mapping[str, Any] | None
    scores: Mapping[str, Any]


@dataclass(frozen=True, kw_only=True)
class WriteInput:
    name: str
    rows: Sequence[WriteRow]
    column_keys: Mapping[str, ColumnKey]
    ncols: int
    log_mode: LogMode


@dataclass(frozen=True, kw_only=True)
class WriteResult:
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

    def write(self, payload: WriteInput) -> WriteResult: ...
