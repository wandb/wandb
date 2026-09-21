from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, get_args

from typing_extensions import override

import wandb
from wandb.errors import UsageError
from wandb.sdk.data_types.eval_table._factory import (
    Backend,
    create_default_writer,
    create_writer,
)
from wandb.sdk.data_types.eval_table._weave import validate_weave_cell_value
from wandb.sdk.data_types.eval_table._writer import (
    Writer,
    WriteInput,
    WriteResult,
    WriteRow,
)
from wandb.sdk.data_types.table import ColumnKey, InputRow, LogMode, Table
from wandb.sdk.lib import telemetry

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

    from wandb.sdk.wandb_run import Run as LocalRun


EVAL_TABLE_ROW_INDEX_KEY = "row"
UnsupportedMediaMode = Literal["stub", "raise"]
_UNSUPPORTED_MEDIA_MODES = get_args(UnsupportedMediaMode)


def validate_unsupported_media_mode(mode: str) -> None:
    if mode not in _UNSUPPORTED_MEDIA_MODES:
        raise ValueError(
            "unsupported_media_mode must be one of "
            f"{_UNSUPPORTED_MEDIA_MODES}, got {mode!r}."
        )


class EvalTable(Table):
    """A Table subclass that routes run.log() to the new Eval Tables experience.

    When logged via run.log(), an EvalTable is logged as a Weave Eval via
    weave.EvaluationLogger instead of being uploaded as a regular wandb Table
    artifact.

    Note: EvalTable is a work-in-progress and is NOT yet officially released or
    supported.
    """

    # SDK-side WBValue discriminator, not to be confused by `_type` written to the run
    # history entry.
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
        backend: Backend | None = None,
        unsupported_media_mode: UnsupportedMediaMode = "stub",
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
            backend: Optional storage-backend override. If omitted, the default is
                "weave", which is currently the only supported backend.
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

        validate_unsupported_media_mode(unsupported_media_mode)
        self._writer: Writer | None = (
            create_writer(
                backend,
                unsupported_media_mode=unsupported_media_mode,
            )
            if backend is not None
            else None
        )
        self._unsupported_media_mode = unsupported_media_mode

        self._input_columns = list(input_columns or [])
        self._output_columns = list(output_columns or [])
        self._score_columns = list(score_columns or [])
        self._immutable_write_result: WriteResult | None = None
        self._run_log_key: str | None = None

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

        <!-- lazydoc-ignore -->
        """
        # TODO: Remove when we add support for offline mode
        if run.offline:
            raise UsageError(
                "EvalTable does not support offline mode yet. "
                "Use wandb.init(mode='online') or unset WANDB_MODE."
            )

        writer = self._writer
        if writer is None:
            # Select the default writer here so its choice can depend on the run.
            writer = create_default_writer(
                run,
                unsupported_media_mode=self._unsupported_media_mode,
            )

        # Initialize writer with run context while intentionally
        # skipping the file-copy behavior in Table.bind_to_run().
        writer.bind_to_run(run, str(key), step)
        self._writer = writer
        self._run = run
        self._run_log_key = str(key)

    @override
    def to_json(self, run_or_artifact: Any) -> dict[str, Any]:
        """Returns the JSON representation expected by the backend.

        <!-- lazydoc-ignore -->
        """
        if isinstance(run_or_artifact, wandb.Artifact):
            raise TypeError("EvalTable cannot be logged to a wandb.Artifact.")
        if not isinstance(run_or_artifact, wandb.Run):
            raise TypeError("EvalTable can only be serialized for a wandb.Run.")

        run = run_or_artifact

        writer = self._writer
        if writer is None or self._run_log_key is None:
            raise UsageError("EvalTable must be logged with run.log().")

        # This check also ensures that we've initialized Weave via bind_to_run.
        if self._run is not run:
            raise UsageError(
                "EvalTable cannot be serialized for a different run than it was "
                "bound to."
            )

        if self._immutable_write_result is not None:
            self._warn_immutable_already_logged()
            return dict(self._immutable_write_result.marker)

        result = writer.write(self._prepare_write_input(self._run_log_key))
        self._immutable_write_result = result

        with telemetry.context(run=run) as tel:
            tel.feature.eval_table = True

        return dict(result.marker)

    @override
    def has_been_logged(self) -> bool:
        return self._immutable_write_result is not None

    def _validate_cell_value(self, val: Any, col: ColumnKey) -> None:
        if self._writer is not None:
            self._writer.validate_cell_value(val, col)
        else:
            validate_weave_cell_value(
                val,
                col,
                self._unsupported_media_mode,
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
                f"for EvalTable logging. Duplicate column name(s): {duplicates}."
            )
        return columns

    def _warn_immutable_already_logged(self) -> None:
        wandb.termwarn(
            "EvalTable with log_mode='IMMUTABLE' has already been logged. "
            "Subsequent run.log() calls have no effect.",
            repeat=False,
        )

    def _prepare_write_input(self, name: str) -> WriteInput:
        self._validate_column_mappings(
            self._input_columns,
            self._output_columns,
            self._score_columns,
        )

        # Any column not listed in a role defaults to an output column.
        str_columns = self._string_columns()
        column_keys = dict(zip(str_columns, self.columns, strict=True))
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

        rows: list[WriteRow] = []
        for row_idx, row in enumerate(self.data, start=1):
            values = dict(zip(str_columns, row, strict=True))
            if inject_row_index:
                inputs: dict[str, Any] = {EVAL_TABLE_ROW_INDEX_KEY: row_idx}
            else:
                inputs = {col: values[col] for col in self._input_columns}

            # Always use a dict so backends see a stable column-keyed shape;
            # single-output is no exception.
            if output_cols:
                output: dict[str, Any] | None = {
                    col: values[col] for col in output_cols
                }
            else:
                output = None

            scores = {col: values[col] for col in self._score_columns}
            rows.append(WriteRow(inputs=inputs, output=output, scores=scores))

        return WriteInput(
            name=name,
            rows=rows,
            column_keys=column_keys,
            ncols=len(self.columns),
            log_mode=self.log_mode,
        )
