from __future__ import annotations

import datetime
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

import wandb
import wandb.integration.weave as weave_integration
import wandb.integration.weave.media_adapters as media_adapters
from wandb.sdk.data_types.base_types.media import _numpy_arrays_to_lists

if TYPE_CHECKING:
    from wandb.sdk.data_types.table import ColumnKey, LogMode
    from wandb.sdk.wandb_run import Run as LocalRun


EVAL_TABLE_MARKER = {"wandb_eval_table": True}

_MIN_WEAVE_VERSION = "0.52.41"


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


def _is_numpy_datetime64(value: Any) -> bool:
    # Optional import: only imports NumPy if it is already installed.
    np = wandb.util.np
    return np is not None and isinstance(value, np.datetime64)


def _is_datetime_like(value: Any) -> bool:
    return isinstance(value, datetime.date) or _is_numpy_datetime64(value)


def _normalize_numpy_datetime64(value: Any) -> datetime.datetime | None:
    # NumPy only converts to Python datetime at microsecond resolution; ns and
    # finer units otherwise become raw integer offsets.
    py_value = value.astype("datetime64[us]").tolist()
    if py_value is None:
        return None
    if isinstance(py_value, datetime.datetime):
        return py_value.replace(tzinfo=datetime.timezone.utc)
    if isinstance(py_value, datetime.date):
        return datetime.datetime(
            py_value.year,
            py_value.month,
            py_value.day,
            tzinfo=datetime.timezone.utc,
        )

    raise TypeError(f"Unexpected numpy.datetime64 conversion result: {py_value!r}")


def _normalize_datetime(value: Any) -> datetime.datetime | None:
    """Normalize datetime-like values for Weave; NumPy NaT becomes None."""
    if isinstance(value, datetime.datetime):
        return value
    if isinstance(value, datetime.date):
        # Weave handles datetime.datetime but not datetime.date.
        return datetime.datetime(
            value.year,
            value.month,
            value.day,
            tzinfo=datetime.timezone.utc,
        )

    return _normalize_numpy_datetime64(value)


def _normalize_non_media_value(value: Any) -> Any:
    if _is_datetime_like(value):
        return _normalize_datetime(value)

    value = _numpy_arrays_to_lists(value)

    # Normalize scalar NumPy values and other simple values like Table does.
    value, _ = wandb.util.json_friendly(value)

    if isinstance(value, dict):
        return {key: _normalize_non_media_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_non_media_value(item) for item in value]

    return value


class WeaveEvalTableWriter:
    def __init__(
        self,
        *,
        unsupported_media_mode: media_adapters.UnsupportedMediaMode,
    ) -> None:
        weave_integration.ensure_version(
            _MIN_WEAVE_VERSION,
            'EvalTable dependency error. Fix with: `pip install wandb["eval-table"]`.',
        )
        media_adapters.validate_unsupported_media_mode(unsupported_media_mode)
        self._unsupported_media_mode = unsupported_media_mode

    def bind(self, run: LocalRun, key: str, step: int | str) -> None:
        # Other writers use run/key/step to derive stable idempotency keys, so
        # keep the full logging location in the shared protocol.
        del key, step
        weave_integration.init_weave(run.entity, run.project)

    def validate_cell_value(self, value: Any, column: ColumnKey) -> None:
        media_adapters.validate_supported_value(
            value,
            column,
            unsupported_media_mode=self._unsupported_media_mode,
        )

    def write(self, payload: EvalTableWriteInput) -> EvalTableWriteResult:
        from weave.evaluation.eval_imperative import EvaluationLogger

        evaluation = EvaluationLogger._create_with_meta(
            EVAL_TABLE_MARKER,
            name=payload.name,
        )
        for row in payload.rows:
            evaluation.log_example(
                inputs=self._normalize_mapping(row.inputs, payload.column_keys),
                output=(
                    self._normalize_mapping(row.output, payload.column_keys)
                    if row.output is not None
                    else None
                ),
                scores=self._normalize_mapping(row.scores, payload.column_keys),
            )

        evaluation.log_summary()
        # TODO: We should work with Weave on exposing a public evaluate_call_id()
        # instead of relying on this private field.
        evaluate_call_id = evaluation._evaluate_call.id
        return EvalTableWriteResult(
            marker={
                "_type": "eval-table",
                "ncols": payload.ncols,
                "nrows": len(payload.rows),
                "log_mode": payload.log_mode,
                "evaluate_call_id": evaluate_call_id,
            },
            logged_id=evaluate_call_id,
        )

    def _normalize_mapping(
        self,
        values: Mapping[str, Any],
        column_keys: Mapping[str, ColumnKey],
    ) -> dict[str, Any]:
        return {
            column: self._normalize_value(item, column_keys.get(column, column))
            for column, item in values.items()
        }

    def _normalize_value(self, value: Any, column: ColumnKey) -> Any:
        """Adapt media, then apply Table-like normalization for plain values.

        TODO: Media stubbing is temporary until every backend supports these values.
        """
        value = media_adapters.unwrap_value(
            value,
            column,
            unsupported_media_mode=self._unsupported_media_mode,
        )
        value = media_adapters.handle_nested_wandb_values(
            value,
            column,
            self._unsupported_media_mode,
        )
        return _normalize_non_media_value(value)
