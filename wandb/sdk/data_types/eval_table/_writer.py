from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from wandb.sdk.data_types.table import ColumnKey, LogMode
    from wandb.sdk.wandb_run import Run as LocalRun


@dataclass(frozen=True, kw_only=True)
class WriteRow:
    """One row partitioned by role and keyed by original Table columns."""

    inputs: Mapping[ColumnKey, Any]
    output: Mapping[ColumnKey, Any] | None
    scores: Mapping[ColumnKey, Any]


@dataclass(frozen=True, kw_only=True)
class WriteResult:
    """The run-history marker and backend ID produced by a write."""

    marker: Mapping[str, Any]
    logged_id: str


class EvalTableWriter(Protocol):
    """Backend-specific validation and persistence for an EvalTable."""

    def validate_cell_value(self, value: Any, column: ColumnKey) -> None:
        """Raise if the backend cannot represent a value from this column.

        This may run before `bind_to_run` while Table constructs its rows.
        """
        ...

    def bind_to_run(self, run: LocalRun, key: str, step: int | str) -> None:
        """Bind backend state before `write` to this run-history location."""
        ...

    def write(
        self,
        *,
        name: str,
        rows: Sequence[WriteRow],
        ncols: int,
        log_mode: LogMode,
    ) -> WriteResult:
        """Persist an EvalTable and return its backend-owned history marker.

        EvalTable caches a successful result; a failed call may be retried. The
        result's `logged_id` identifies the evaluation written by this backend.

        Row mappings retain the Table's original string or integer column keys.
        The backend converts those keys to its wire format while retaining the
        originals for validation errors. `ncols` is the total Table column count,
        including columns that may not appear in a particular role mapping.
        """
        ...
