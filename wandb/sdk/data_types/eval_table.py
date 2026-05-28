from __future__ import annotations

import atexit
import importlib
import sys
import warnings
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any, Literal, cast

from packaging.version import parse as parse_version
from typing_extensions import override

import wandb
from wandb.errors import UsageError
from wandb.integration.weave.weave import setup_with_import
from wandb.sdk.data_types.table import Table

if TYPE_CHECKING:
    from typing import Protocol

    from wandb.sdk.wandb_run import Run as LocalRun

    class _EvaluateCall(Protocol):
        id: str

    class _EvaluationLogger(Protocol):
        _evaluate_call: _EvaluateCall

        def log_example(
            self,
            inputs: dict[str, Any],
            output: Any,
            scores: dict[str, float | bool | dict],
        ) -> None: ...

        def log_summary(
            self,
            summary: dict[str, Any] | None = None,
            auto_summarize: bool = True,
        ) -> None: ...

    class _EvaluationLoggerCls(Protocol):
        def _create_with_meta(
            self,
            eval_meta: dict[str, Any],
            *,
            name: str | None = None,
            **kwargs: Any,
        ) -> _EvaluationLogger: ...


EVAL_TABLE_MARKER = {"wandb_eval_table": True}

EVAL_TABLE_ROW_INDEX_KEY = "row"

_MIN_WEAVE_VERSION = "0.52.41"
_EVAL_TABLE_WEAVE_DEP_MSG = (
    "`wandb.EvalTable` is missing weave dependency. "
    'Install it with `pip install wandb["eval-table"]`.'
)


def _get_evaluation_logger_cls(run: LocalRun) -> _EvaluationLoggerCls:
    try:
        entity = run.entity
    except AttributeError:
        entity = None
    try:
        project = run.project
    except AttributeError:
        project = None

    try:
        if not setup_with_import(entity, project):
            raise RuntimeError(
                "Weave logging is disabled (WANDB_DISABLE_WEAVE is set). "
                "Unset it or use run.log() with a regular Table to suppress this."
            )
    except ImportError as e:
        raise ImportError(_EVAL_TABLE_WEAVE_DEP_MSG) from e

    weave = sys.modules["weave"]
    try:
        weave_version = weave.__version__
    except AttributeError as e:
        raise ImportError(_EVAL_TABLE_WEAVE_DEP_MSG) from e

    if parse_version(weave_version) < parse_version(_MIN_WEAVE_VERSION):
        raise ImportError(
            "`wandb.EvalTable` requires "
            f"weave>={_MIN_WEAVE_VERSION}; found weave=={weave_version}. "
            "Install it with "
            '`pip install wandb["eval-table"]`.'
        )

    try:
        eval_imperative = importlib.import_module("weave.evaluation.eval_imperative")
    except Exception as e:
        raise ImportError(_EVAL_TABLE_WEAVE_DEP_MSG) from e

    return cast("_EvaluationLoggerCls", eval_imperative.EvaluationLogger)


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
        columns=None,
        data=None,
        rows=None,
        dataframe=None,
        dtype=None,
        optional=True,
        allow_mixed_types=False,
        log_mode: Literal["IMMUTABLE", "MUTABLE", "INCREMENTAL"] | None = "IMMUTABLE",
        *,
        input_columns: list[str] | None = None,
        output_columns: list[str] | None = None,
        score_columns: list[str] | None = None,
        unsupported_media_mode: Literal["raise", "stub"] = "raise",
    ) -> None:
        """Initializes an EvalTable object.

        Supports arguments of parent Table class except where noted below.

        Args:
            columns: (List[str]) Names of the columns in the table.
                If unset, but input_columns, output_columns, or score_columns are set,
                then we'll just set columns to the union of those, in that order.
            log_mode: (str) Controls how the table is logged when the same EvalTable
                is passed to ``run.log()`` more than once.
                - "IMMUTABLE" (default): full table logged on first ``run.log()``;
                  subsequent ``run.log()`` calls are no-ops.
                - "INCREMENTAL": each ``run.log()`` appends new rows since the last
                  call to the same eval. Defers logging the summary and closing out
                  the eval until ``finish()`` or process exit.
                - "MUTABLE": each ``run.log()`` logs a fresh eval with the current table
                  contents and summary. Provided for backward compatibility with Table
                  and not recommended.
            input_columns: (List[str]) Names of the input columns.
                If set, designates these columns as inputs. Eval comparisons will match
                rows based on matching values from input columns. If unset, we will
                inject a "row" index input column so comparisons can match against that.
            output_columns: (List[str]) Names of the output columns.
                These represents the values to be compared. Any columns not designated
                as input, output, or score will default to being output columns.
            score_columns: (List[str]) Names of the score columns.
                These represent derived scores for the outputs. By default, we will
                auto-summarize any numeric and boolean scores.
            unsupported_media_mode: How to handle unsupported wandb media/value types.
                - "raise" (default): fail fast when unsupported values are added.
                - "stub": log unsupported values as short placeholder strings
                  like "[wandb.Html unsupported: abc12345]". (This is a temporary flag
                  for use during development.)

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

            et4 = wandb.EvalTable(
                input_columns=["image"],
                output_columns=["prediction"],
                score_columns=["score"],
                data=[[pil_image, "4", 0.5]],
            )
            et4.set_summary({"val_loss": 0.3})
            run.log({"my_eval_4": et4})
            # You can set eval-level summary scores.

            et5 = wandb.EvalTable(
                input_columns=["epoch", "image"],
                output_columns=["prediction"],
                score_columns=["score"],
                log_mode="INCREMENTAL",
            )
            for epoch in range(num_epochs):
                for pil_image in validation_images:
                    prediction, score = evaluate_one_image(epoch, pil_image)
                    et5.add_data(epoch, pil_image, prediction, score)
                run.log({"my_eval_5": et5})
            et5.log_summary({"val_loss": 0.3})
            # In INCREMENTAL mode, we'll keep logging to the same eval and leave it
            # open until you call log_summary() or finish().
        """
        self._input_columns: list[str] = list(input_columns or [])
        self._output_columns: list[str] = list(output_columns or [])
        self._score_columns: list[str] = list(score_columns or [])
        self._summary: dict | None = None
        self._auto_summarize: bool = True
        # INCREMENTAL mode reuses one logger so all batches land in the same
        # eval. It does not trigger any of the artifact-related code in normal tables,
        # including in table_decorators::allow_incremental_logging_after_append().
        # IMMUTABLE/MUTABLE use local loggers and only persist call ids.
        self._incremental_eval_logger: _EvaluationLogger | None = None
        self._immutable_evaluate_call_id: str | None = None
        # Track separately from self._last_logged_idx used by normal INCREMENTAL tables
        # to avoid conflating our somewhat different semantics.
        self._last_weave_logged_idx: int | None = None
        self._is_incremental_finished = False
        self._run_log_key: str | None = None
        from wandb.integration.weave.media_adapters import (
            validate_unsupported_media_mode,
        )

        validate_unsupported_media_mode(unsupported_media_mode)
        self._unsupported_media_mode = unsupported_media_mode

        # Derive columns from role lists if columns arg omitted, so users
        # don't have to double-name columns when they've already listed
        # them in input/output/score_columns. Skip if a dataframe is given
        # — Table infers columns from the dataframe and ignores `columns`.
        if (
            columns is None
            and dataframe is None
            and (self._input_columns or self._output_columns or self._score_columns)
        ):
            columns = self._input_columns + self._output_columns + self._score_columns

        super().__init__(
            columns=columns,
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
        key: str,
        step: int,
        id_: int | None = None,
        ignore_copy_err: bool | None = None,
    ) -> None:
        """Bind this object to a run.

        <!-- lazydoc-ignore: internal -->
        """
        # Store context for to_json; skip the file-copy that Table.bind_to_run does.
        self._run = run
        self._run_log_key = key

    @override
    def to_json(self, run_or_artifact: Any) -> dict:
        """Returns the JSON representation expected by the backend.

        <!-- lazydoc-ignore: internal -->
        """
        if self._is_incremental_finished:
            raise UsageError("Cannot log an EvalTable after finish() has been called.")

        if isinstance(run_or_artifact, wandb.Artifact):
            raise TypeError("EvalTable cannot be logged to a wandb.Artifact.")

        run = cast("LocalRun", run_or_artifact)

        # TODO: Remove when weave adds support for offline mode
        if run.offline:
            raise UsageError(
                "EvalTable does not support offline mode yet. "
                "Use wandb.init(mode='online') or unset WANDB_MODE."
            )

        # Run context: route to Weave EvaluationLogger.
        if self._run_log_key is None:
            raise UsageError("EvalTable must be logged with run.log().")
        evaluate_call_id = self._log_to_weave(run, self._run_log_key)

        return {
            "_type": "eval-table",
            "ncols": len(self.columns),
            "nrows": len(self.data),
            "log_mode": self.log_mode,
            "evaluate_call_id": evaluate_call_id,
        }

    @override
    def _has_been_logged(self) -> bool:
        match self.log_mode:
            case "IMMUTABLE":
                return self._immutable_evaluate_call_id is not None
            case "INCREMENTAL":
                return (
                    self._incremental_eval_logger is not None
                    or self._last_weave_logged_idx is not None
                )
            case "MUTABLE":
                return self._run is not None
            case _:
                return False

    @override
    def _reset_logging_state_after_mutation(self) -> None:
        super()._reset_logging_state_after_mutation()
        self._run_log_key = None

    def _validate_cell_value(self, val: Any, row_idx: int, col: str | int) -> None:
        from wandb.integration.weave.media_adapters import validate_supported_value

        validate_supported_value(
            val,
            col,
            row_idx=row_idx,
            unsupported_media_mode=self._unsupported_media_mode,
        )

    @override
    def add_data(self, *data: Any) -> None:
        if len(data) == len(self.columns):
            row_idx = len(self.data)
            for col, val in zip(self.columns, data, strict=True):
                self._validate_cell_value(val, row_idx, col)

        super().add_data(*data)

    @override
    def add_column(self, name: Any, data: Any, optional: bool = False) -> None:
        if self.log_mode != "INCREMENTAL" and (
            isinstance(data, list) or wandb.util.is_numpy_array(data)
        ):
            for row_idx, val in enumerate(data):
                self._validate_cell_value(val, row_idx, name)

        super().add_column(name, data, optional=optional)

    def _validate_column_mappings(
        self,
        input_cols: list[str],
        output_cols: list[str],
        score_cols: list[str],
    ) -> None:
        all_assigned = set(input_cols) | set(output_cols) | set(score_cols)
        table_cols = set(self.columns)

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
                warnings.warn(
                    f"Column {col!r} appears in more than one role list; "
                    "it will be included in all matching dicts.",
                    stacklevel=3,
                )
            seen.add(col)

    def set_summary(
        self, summary: dict | None = None, auto_summarize: bool = True
    ) -> None:
        """Set the summary passed to EvaluationLogger.log_summary when logged."""
        self._summary = summary
        self._auto_summarize = auto_summarize

    def log_summary(
        self, summary: dict | None = None, auto_summarize: bool = True
    ) -> None:
        """Set the summary and finalize an INCREMENTAL EvalTable."""
        if self._is_incremental_finished:
            wandb.termwarn(
                "EvalTable.log_summary() called after the EvalTable was already "
                "finished. The new summary will not be logged.",
                repeat=False,
            )
            return

        self.set_summary(summary, auto_summarize=auto_summarize)
        self.finish()

    def finish(self) -> None:
        """Finalize an INCREMENTAL EvalTable after all rows have been logged."""
        if self.log_mode != "INCREMENTAL":
            raise UsageError(
                "EvalTable.finish() is only supported for log_mode='INCREMENTAL'."
            )

        if self._is_incremental_finished:
            return

        ev = self._incremental_eval_logger
        if ev is None:
            raise UsageError(
                "EvalTable.finish() requires the EvalTable to be logged with "
                "run.log() first."
            )

        pending_rows = self._num_unlogged_rows()
        if pending_rows:
            wandb.termwarn(
                f"EvalTable.finish() called with {pending_rows} row(s) added "
                "after the last run.log(); those rows will not be included in "
                "the finalized evaluation.",
                repeat=False,
            )

        ev.log_summary(self._summary, auto_summarize=self._auto_summarize)
        self._is_incremental_finished = True

    def _iter_unwrapped_rows(self, start: int = 0) -> Iterator[dict[str, Any]]:
        from wandb.integration.weave.media_adapters import unwrap_value

        cols = self.columns
        warned: set[type] = set()
        for row in self.data[start:]:
            yield {
                col: unwrap_value(
                    val,
                    col,
                    warned,
                    unsupported_media_mode=self._unsupported_media_mode,
                )
                for col, val in zip(cols, row, strict=True)
            }

    def _create_weave_eval_logger(
        self, run: LocalRun, eval_name: str
    ) -> _EvaluationLogger:
        self._validate_column_mappings(
            self._input_columns, self._output_columns, self._score_columns
        )

        # Verify weave is installed AND new enough for EvalTable's needs before
        # attempting to use it. Catches both missing-install and version-skew
        # cases with a single, EvalTable-attributed error.
        EvaluationLogger = _get_evaluation_logger_cls(run)  # noqa: N806

        return EvaluationLogger._create_with_meta(
            EVAL_TABLE_MARKER,
            name=eval_name,
        )

    def _setup_incremental_weave_eval_logger(
        self, run: LocalRun, eval_name: str
    ) -> _EvaluationLogger:
        """Build the INCREMENTAL EvaluationLogger on first use."""
        if self._incremental_eval_logger is not None:
            return self._incremental_eval_logger

        self._incremental_eval_logger = self._create_weave_eval_logger(run, eval_name)

        # INCREMENTAL evals defer summary/finalization until `finish()` or
        # process exit. Register an atexit handler that fires before weave's
        # own EvaluationLogger cleanup: atexit runs in LIFO order, and weave
        # registered its `_cleanup_all_evaluations` at module import.
        atexit.register(self._summarize_at_exit)

        return self._incremental_eval_logger

    def _summarize_at_exit(self) -> None:
        """Fire `log_summary` if this EvalTable has not been finished yet."""
        ev = self._incremental_eval_logger
        if ev is None or self._is_incremental_finished:
            return
        pending_rows = self._num_unlogged_rows()
        if pending_rows:
            wandb.termwarn(
                f"EvalTable process-exit cleanup found {pending_rows} row(s) "
                "added after the last run.log(); those rows will not be "
                "included in the finalized evaluation.",
                repeat=False,
            )
        try:
            ev.log_summary(self._summary, auto_summarize=self._auto_summarize)
            self._is_incremental_finished = True
        except Exception:
            # Best-effort cleanup; don't raise during atexit.
            pass

    def _num_unlogged_rows(self) -> int:
        if self.log_mode != "INCREMENTAL":
            raise UsageError(
                "EvalTable._num_unlogged_rows() is only supported for "
                "log_mode='INCREMENTAL'."
            )
        if self._last_weave_logged_idx is None:
            return len(self.data)
        return max(0, len(self.data) - self._last_weave_logged_idx - 1)

    def _log_to_weave(self, run: LocalRun, eval_name: str) -> str:
        if self._is_incremental_finished:
            raise UsageError("Cannot log an EvalTable after finish() has been called.")

        # IMMUTABLE: only the first run.log() should fire the weave path.
        # The framework may still call to_json on subsequent log()s, but
        # the eval has already been logged in full and summarized.
        if (
            self.log_mode == "IMMUTABLE"
            and self._immutable_evaluate_call_id is not None
        ):
            wandb.termwarn(
                "EvalTable with log_mode='IMMUTABLE' has already been logged. "
                "Subsequent run.log() calls have no effect. Set "
                "log_mode='MUTABLE' or log_mode='INCREMENTAL' to log updates.",
                repeat=False,
            )
            return self._immutable_evaluate_call_id

        if self.log_mode == "INCREMENTAL":
            ev = self._setup_incremental_weave_eval_logger(run, eval_name)
        else:
            ev = self._create_weave_eval_logger(run, eval_name)

        # Any column not listed in a role defaults to an output column.
        assigned = (
            set(self._input_columns)
            | set(self._output_columns)
            | set(self._score_columns)
        )
        output_cols = self._output_columns + [
            c for c in self.columns if c not in assigned
        ]

        # When no input columns are designated, inject a synthetic 1-indexed `row`
        # input so each row has a distinct digest for comparison. We avoid
        # injecting when input columns exist so row-index matching doesn't
        # leak into the input-equality criteria.
        inject_row_index = not self._input_columns

        # INCREMENTAL logs only rows added since the last EvalTable log.
        # IMMUTABLE/MUTABLE always log all rows from scratch.
        if self.log_mode == "INCREMENTAL":
            last_idx = self._last_weave_logged_idx
            start_idx = last_idx + 1 if last_idx is not None else 0
        else:
            start_idx = 0

        for offset, row in enumerate(self._iter_unwrapped_rows(start=start_idx)):
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

        if self.log_mode == "INCREMENTAL":
            self._last_weave_logged_idx = len(self.data) - 1

        if self.log_mode in ("IMMUTABLE", "MUTABLE"):
            ev.log_summary(self._summary, auto_summarize=self._auto_summarize)
            if self.log_mode == "IMMUTABLE":
                # TODO: We should work with Weave on exposing a public
                # evaluate_call_id() instead of relying on this private field.
                self._immutable_evaluate_call_id = ev._evaluate_call.id
        # INCREMENTAL: log_summary fires from explicit `finish()` or via the
        # `_summarize_at_exit` atexit handler, using the latest `set_summary` value.
        return ev._evaluate_call.id
