from __future__ import annotations

import datetime
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from typing_extensions import override

import wandb
import wandb.integration.weave as weave_integration
import wandb.integration.weave.media_adapters as media_adapters
from wandb.errors import UsageError
from wandb.sdk.data_types.base_types.media import _numpy_arrays_to_lists
from wandb.sdk.data_types.table import ColumnKey, InputRow, LogMode, Table

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

    from wandb.sdk.wandb_run import Run as LocalRun


EVAL_TABLE_MARKER = {"wandb_eval_table": True}

EVAL_TABLE_ROW_INDEX_KEY = "row"

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
    unsupported_media_mode: media_adapters.UnsupportedMediaMode,
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


class EvalTable(Table):
    """A Table subclass that routes run.log() to the new Eval Tables experience.

    When logged via run.log(), an EvalTable is logged as a Weave Eval via
    weave.EvaluationLogger instead of being uploaded as a regular wandb Table
    artifact.

    Note: EvalTable is a work-in-progress and is NOT yet officially released or
    supported.
    <!-- lazydoc-ignore-class: internal -->
    """

    _log_type = "eval-table"

    def __init__(
        self,
        columns: list[ColumnKey] | None = None,
        data: list[InputRow] | np.ndarray | pd.DataFrame | None = None,
        rows: list[InputRow] | None = None,
        dataframe: pd.DataFrame | None = None,
        dtype: Any = None,
        optional: bool | list[bool] = True,
        allow_mixed_types: bool = False,
        log_mode: LogMode = "IMMUTABLE",
        *,
        input_columns: list[str] | None = None,
        output_columns: list[str] | None = None,
        score_columns: list[str] | None = None,
        unsupported_media_mode: media_adapters.UnsupportedMediaMode = "stub",
    ) -> None:
        """Initializes an EvalTable object.

        Supports arguments of parent Table class except where noted below.

        Warning: Media suport is only partially implemented. We may not save all
        metadata, and media types not yet supported will be replaced with stubs for now.

        Args:
            columns: Names of the columns in the table.
                If unset, but input_columns, output_columns, or score_columns are set,
                then we'll just set columns to the union of those, in that order.
            log_mode: Controls how the table is logged when the same EvalTable
                is passed to `run.log()` more than once.
                - "IMMUTABLE" (default): full table logged on first `run.log()`;
                  subsequent `run.log()` calls are no-ops.
                - "MUTABLE" and "INCREMENTAL": not currently supported for EvalTable.
            input_columns: Names of the input columns.
                If set, designates these columns as inputs. Eval comparisons will match
                rows based on matching values from input columns. If unset, we will
                inject a "row" index input column so comparisons can match against that.
            output_columns: Names of the output columns.
                These represents the values to be compared. Any columns not designated
                as input, output, or score will default to being output columns.
            score_columns: Names of the score columns.
                These represent derived scores for the outputs. By default, we will
                auto-summarize any numeric and boolean scores.
            unsupported_media_mode: How to handle unsupported wandb media/value types.
                - "stub" (default): log unsupported values as short placeholder strings
                  like "[wandb.Html not yet supported]". (This is a temporary flag
                  for use during development.)
                - "raise": fail fast when unsupported wandb value types are added.

        Examples:
            et1 = wandb.EvalTable(
                input_columns=["image"],
                output_columns=["prediction"],
                score_columns=["score"],
                data=[[pil_image, "4", 0.5]],
            )
            run.log({"my_eval_1": et1})
            # If you don't specify columns or dataframe, but specify input, output,
            # and score columns, we will infer the list of columns from the input,
            # output, and score columns, in that order.

            et2 = wandb.EvalTable(
                columns=["image", "prediction", "score"],
                input_columns=["image"],
                score_columns=["score"],
                data=[[pil_image, "4", 0.5]],
            )
            run.log({"my_eval_2": et2})
            # If you specify columns or dataframe, you can assign roles for those
            # existing columns. Any unassigned column will be treated as an output
            # column (e.g. "prediction" in this case).

            et3 = wandb.EvalTable(
                columns=["image", "prediction", "score"],
                data=[[pil_image, "4", 0.5]],
            )
            run.log({"my_eval_3": et3})
            # If you don't assign any input columns, we will auto-inject a numeric
            # "row" index as the input column, and comparisons will match by row
            # index. All columns will be treated as outputs.
        """
        if log_mode != "IMMUTABLE":
            raise UsageError("EvalTable currently only supports log_mode='IMMUTABLE'.")

        weave_integration.ensure_version(
            _MIN_WEAVE_VERSION,
            'EvalTable dependency error. Fix with: `pip install wandb["eval-table"]`.',
        )

        self._input_columns = list(input_columns or [])
        self._output_columns = list(output_columns or [])
        self._score_columns = list(score_columns or [])
        self._immutable_evaluate_call_id: str | None = None
        self._immutable_logged_json: dict[str, Any] | None = None
        self._run_log_key: str | None = None

        media_adapters.validate_unsupported_media_mode(unsupported_media_mode)
        self._unsupported_media_mode = unsupported_media_mode

        # Derive columns from role lists if columns arg omitted, so users
        # don't have to double-name columns when they've already listed
        # them in input/output/score_columns. Skip if a dataframe is given
        # — Table infers columns from the dataframe and ignores `columns`.
        table_columns: list[ColumnKey] | None = columns
        if (
            columns is None
            and dataframe is None
            and (self._input_columns or self._output_columns or self._score_columns)
        ):
            table_columns = [
                *self._input_columns,
                *self._output_columns,
                *self._score_columns,
            ]

        super().__init__(
            columns=table_columns,
            data=data,
            rows=rows,
            dataframe=dataframe,
            dtype=dtype,
            optional=optional,
            allow_mixed_types=allow_mixed_types,
            log_mode=log_mode,
        )

    @override
    def bind_to_run(
        self,
        run: LocalRun,
        key: int | str,
        step: int | str,
        id_: int | str | None = None,
        ignore_copy_err: bool | None = None,
    ) -> None:
        """Bind this object to a run.

        <!-- lazydoc-ignore: internal -->
        """
        # TODO: Remove when weave adds support for offline mode
        if run.offline:
            raise UsageError(
                "EvalTable does not support offline mode yet. "
                "Use wandb.init(mode='online') or unset WANDB_MODE."
            )

        # Now that we have run context, initialize/validate Weave for this project.
        # Skip the file-copy that Table.bind_to_run does.
        weave_integration.init_weave(run.entity, run.project)
        self._run = run
        self._run_log_key = str(key)

    @override
    def to_json(self, run_or_artifact: Any) -> dict[str, Any]:
        """Returns the JSON representation expected by the backend.

        <!-- lazydoc-ignore: internal -->
        """
        if isinstance(run_or_artifact, wandb.Artifact):
            raise TypeError("EvalTable cannot be logged to a wandb.Artifact.")
        if not isinstance(run_or_artifact, wandb.Run):
            raise TypeError("EvalTable can only be serialized for a wandb.Run.")

        run = run_or_artifact

        if self._run_log_key is None:
            raise UsageError("EvalTable must be logged with run.log().")

        # This check also ensures that we've initialized Weave via bind_to_run.
        if self._run is not run:
            raise UsageError(
                "EvalTable cannot be serialized for a different run than it was "
                "bound to."
            )

        if self._immutable_logged_json is not None:
            self._warn_immutable_already_logged()
            return dict(self._immutable_logged_json)

        evaluate_call_id = self._log_to_weave(self._run_log_key)

        json_dict = {
            "_type": "eval-table",
            "ncols": len(self.columns),
            "nrows": len(self.data),
            "log_mode": self.log_mode,
            "evaluate_call_id": evaluate_call_id,
        }
        self._immutable_logged_json = dict(json_dict)
        return json_dict

    @override
    def has_been_logged(self) -> bool:
        return self._immutable_evaluate_call_id is not None

    def _validate_cell_value(self, val: Any, col: ColumnKey) -> None:
        media_adapters.validate_supported_value(
            val,
            col,
            unsupported_media_mode=self._unsupported_media_mode,
        )

    @override
    def add_data(self, *data: Any) -> None:
        if len(data) == len(self.columns):
            for col, val in zip(self.columns, data, strict=True):
                self._validate_cell_value(val, col)

        super().add_data(*data)

    @override
    def add_column(
        self,
        name: str,
        data: list[Any] | np.ndarray,
        optional: bool = False,
    ) -> None:
        if isinstance(data, list) or wandb.util.is_numpy_array(data):
            for val in data:
                self._validate_cell_value(val, name)

        super().add_column(name, data, optional=optional)

    def _validate_column_mappings(
        self,
        input_cols: list[str],
        output_cols: list[str],
        score_cols: list[str],
    ) -> None:
        all_assigned = set(input_cols) | set(output_cols) | set(score_cols)
        table_cols = set(self._string_columns())

        unknown = all_assigned - table_cols
        if unknown:
            raise ValueError(
                f"Column(s) {sorted(unknown)} listed in input/output/score_columns "
                "do not exist in the table."
            )

        # Warn about columns listed in more than one role
        seen: set[str] = set()
        for col in input_cols + output_cols + score_cols:
            if col in seen:
                wandb.termwarn(
                    f"Column {col!r} appears in more than one role list; "
                    "it will be included in all matching dicts.",
                    repeat=False,
                )
            seen.add(col)

    def _string_columns(self) -> list[str]:
        # Table supports both string and int column names; canonicalize to string
        columns = [str(col) for col in self.columns]
        duplicates = sorted({col for col in columns if columns.count(col) > 1})
        if duplicates:
            raise ValueError(
                "EvalTable column names must be unique after converting to strings "
                f"for Weave logging. Duplicate column name(s): {duplicates}."
            )
        return columns

    def _iterrows_for_weave(self, start: int = 0) -> Iterator[dict[str, Any]]:
        str_columns = self._string_columns()
        for row in self.data[start:]:
            yield {
                str_col: _normalize_value(
                    val,
                    col,
                    unsupported_media_mode=self._unsupported_media_mode,
                )
                for col, str_col, val in zip(
                    self.columns,
                    str_columns,
                    row,
                    strict=True,
                )
            }

    def _create_weave_eval_logger(self, eval_name: str) -> Any:
        from weave.evaluation.eval_imperative import EvaluationLogger

        self._validate_column_mappings(
            self._input_columns, self._output_columns, self._score_columns
        )

        return EvaluationLogger._create_with_meta(
            EVAL_TABLE_MARKER,
            name=eval_name,
        )

    def _warn_immutable_already_logged(self) -> None:
        wandb.termwarn(
            "EvalTable with log_mode='IMMUTABLE' has already been logged. "
            "Subsequent run.log() calls have no effect.",
            repeat=False,
        )

    def _log_to_weave(self, eval_name: str) -> str:
        # IMMUTABLE: only the first run.log() should fire the weave path.
        # The framework may still call to_json on subsequent log()s, but
        # the eval has already been logged in full and summarized.
        if (
            self.log_mode == "IMMUTABLE"
            and self._immutable_evaluate_call_id is not None
        ):
            self._warn_immutable_already_logged()
            return self._immutable_evaluate_call_id

        ev = self._create_weave_eval_logger(eval_name)

        # Any column not listed in a role defaults to an output column.
        str_columns = self._string_columns()
        assigned = (
            set(self._input_columns)
            | set(self._output_columns)
            | set(self._score_columns)
        )
        output_cols = self._output_columns + [
            col for col in str_columns if col not in assigned
        ]

        # When no input columns are designated, inject a synthetic 1-indexed `row`
        # input so each row has a distinct digest for comparison. We avoid
        # injecting when input columns exist so row-index matching doesn't
        # leak into the input-equality criteria.
        inject_row_index = not self._input_columns

        start_idx = 0

        for offset, row in enumerate(self._iterrows_for_weave(start=start_idx)):
            row_idx = start_idx + offset + 1  # 1-indexed cumulative
            if inject_row_index:
                inputs: dict[str, Any] = {EVAL_TABLE_ROW_INDEX_KEY: row_idx}
            else:
                inputs = {col: row[col] for col in self._input_columns}

            # Always use a dict so weave/Compare Evaluations sees a stable
            # shape and column-keyed structure; single-output is no exception.
            if output_cols:
                output: Any = {col: row[col] for col in output_cols}
            else:
                output = None

            scores = {col: row[col] for col in self._score_columns}

            ev.log_example(inputs=inputs, output=output, scores=scores)

        ev.log_summary()
        # TODO: We should work with Weave on exposing a public evaluate_call_id()
        # instead of relying on this private field.
        self._immutable_evaluate_call_id = ev._evaluate_call.id
        return ev._evaluate_call.id
