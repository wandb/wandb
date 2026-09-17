from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from wandb.sdk.data_types.table import ColumnKey, LogMode
    from wandb.sdk.wandb_run import Run as LocalRun


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
    """Backend-owned run-history marker and its backend-specific identifier.

    Writers return complete, intentionally separate marker formats rather than
    sharing an envelope; for example, Weave uses `_type: "eval-table"` while
    CES uses `_type: "eval-table-ces"`.
    """

    marker: Mapping[str, Any]
    logged_id: str


class EvalTableWriter(Protocol):
    """Persist one EvalTable and return its backend-owned history marker.

    `validate_cell_value` may run before `bind` while Table constructs its rows.
    `bind` establishes the run context and precedes `write`. A successful write
    is cached, while a failed write may be retried. `logged_id` identifies the
    evaluation written by the selected backend.
    """

    def bind(self, run: LocalRun, key: str, step: int | str) -> None: ...

    def validate_cell_value(self, value: Any, column: ColumnKey) -> None: ...

    def write(self, payload: EvalTableWriteInput) -> EvalTableWriteResult: ...
