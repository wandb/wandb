from __future__ import annotations

import datetime
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

import wandb
import wandb.integration.weave as weave_integration
import wandb.integration.weave.media_adapters as media_adapters
from wandb.sdk.data_types.base_types.media import _numpy_arrays_to_lists
from wandb.sdk.data_types.eval_table._writer import WriteResult, WriteRow

if TYPE_CHECKING:
    from wandb.sdk.data_types.table import ColumnKey, LogMode
    from wandb.sdk.wandb_run import Run as LocalRun


EVAL_TABLE_MARKER = {"wandb_eval_table": True}

_MIN_WEAVE_VERSION = "0.52.41"


def _is_numpy_datetime64(val: Any) -> bool:
    # Optional import: only imports numpy if it is already installed.
    np = wandb.util.np
    return np is not None and isinstance(val, np.datetime64)


def _is_datetime_like(val: Any) -> bool:
    return isinstance(val, datetime.date) or _is_numpy_datetime64(val)


def _normalize_numpy_datetime64(val: Any) -> datetime.datetime | None:
    # Cast to microseconds before tolist() so NumPy does unit-aware conversion
    # to Python datetime instead of returning raw int offsets for ns/finer units.
    py_val = val.astype("datetime64[us]").tolist()
    if py_val is None:
        return None
    if isinstance(py_val, datetime.datetime):
        return py_val.replace(tzinfo=datetime.timezone.utc)
    if isinstance(py_val, datetime.date):
        return datetime.datetime(
            py_val.year,
            py_val.month,
            py_val.day,
            tzinfo=datetime.timezone.utc,
        )

    raise TypeError(f"Unexpected numpy.datetime64 conversion result: {py_val!r}")


def _normalize_datetime(val: Any) -> datetime.datetime | None:
    """Normalize datetime-like values for Weave; numpy NaT becomes None."""
    if isinstance(val, datetime.datetime):
        return val
    if isinstance(val, datetime.date):
        # Weave handles datetime.datetime but not datetime.date, so normalize.
        return datetime.datetime(
            val.year,
            val.month,
            val.day,
            tzinfo=datetime.timezone.utc,
        )

    return _normalize_numpy_datetime64(val)


def _normalize_non_media_value(val: Any) -> Any:
    if _is_datetime_like(val):
        return _normalize_datetime(val)

    val = _numpy_arrays_to_lists(val)

    # Normalize scalar NumPy values and other simple values like Table does.
    val, _ = wandb.util.json_friendly(val)

    if isinstance(val, dict):
        return {key: _normalize_non_media_value(value) for key, value in val.items()}
    if isinstance(val, (list, tuple)):
        return [_normalize_non_media_value(item) for item in val]

    return val


def _normalize_value(
    val: Any,
    col: str | int,
    *,
    unsupported_media_mode: str,
) -> Any:
    """Normalize a cell value into the Python value passed to Weave.

    This first adapts or stubs wandb media/value types, then applies Table-like
    normalization for plain values such as NumPy scalars, datetimes, and
    containers.

    TODO: The stubbing of wandb media types is temporary until we add full support.
    """
    val = media_adapters.unwrap_value(
        val,
        col,
        unsupported_media_mode=unsupported_media_mode,
    )
    val = media_adapters.handle_nested_wandb_values(
        val,
        col,
        unsupported_media_mode,
    )
    return _normalize_non_media_value(val)


def validate_weave_cell_value(
    val: Any,
    col: ColumnKey,
    unsupported_media_mode: str,
) -> None:
    media_adapters.validate_supported_value(
        val,
        col,
        unsupported_media_mode=unsupported_media_mode,
    )


class WeaveWriter:
    def __init__(
        self,
        *,
        unsupported_media_mode: str,
    ) -> None:
        weave_integration.ensure_version(
            _MIN_WEAVE_VERSION,
            'EvalTable dependency error. Fix with: `pip install wandb["eval-table"]`.',
        )
        self._unsupported_media_mode = unsupported_media_mode

    def bind_to_run(self, run: LocalRun, key: str, step: int | str) -> None:
        # Other writers use run/key/step to derive stable idempotency keys, so
        # keep the full logging location in the shared protocol.
        del key, step

        # Now that we have run context, initialize/validate Weave for this project.
        weave_integration.init_weave(run.entity, run.project)

    def validate_cell_value(self, value: Any, column: ColumnKey) -> None:
        validate_weave_cell_value(
            value,
            column,
            self._unsupported_media_mode,
        )

    def _normalize_mapping(
        self,
        values: Mapping[ColumnKey, Any],
    ) -> dict[str, Any]:
        return {
            str(column): _normalize_value(
                item,
                column,
                unsupported_media_mode=self._unsupported_media_mode,
            )
            for column, item in values.items()
        }

    def _create_weave_eval_logger(self, eval_name: str) -> Any:
        from weave.evaluation.eval_imperative import EvaluationLogger

        return EvaluationLogger._create_with_meta(
            EVAL_TABLE_MARKER,
            name=eval_name,
        )

    def write(
        self,
        *,
        name: str,
        rows: Sequence[WriteRow],
        ncols: int,
        log_mode: LogMode,
    ) -> WriteResult:
        # Import after bind initializes Weave for the intended run project.
        ev = self._create_weave_eval_logger(name)

        for row in rows:
            ev.log_example(
                inputs=self._normalize_mapping(row.inputs),
                output=(
                    self._normalize_mapping(row.output)
                    if row.output is not None
                    else None
                ),
                scores=self._normalize_mapping(row.scores),
            )

        ev.log_summary()
        # TODO: We should work with Weave on exposing a public evaluate_call_id()
        # instead of relying on this private field.
        evaluate_call_id = ev._evaluate_call.id
        return WriteResult(
            history_value={
                "_type": "eval-table",
                "ncols": ncols,
                "nrows": len(rows),
                "log_mode": log_mode,
                "evaluate_call_id": evaluate_call_id,
            },
            logged_id=evaluate_call_id,
        )
