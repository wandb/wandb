from __future__ import annotations

import atexit
import warnings
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any, Literal

import wandb
from wandb.errors import UsageError
from wandb.sdk.data_types.table import Table

if TYPE_CHECKING:
    from wandb.sdk.wandb_run import Run as LocalRun


EVAL_TABLE_MARKER = {"wandb_eval_table": True}

EVAL_TABLE_ROW_INDEX_KEY = "row"


# TODO: Add required dep from wandb to weave. In the meantime, use reflection to verify
# that we've installed a weave version with what we need.
def _import_evaluation_logger() -> Any:
    """Import and return weave's EvaluationLogger, verifying it's new enough."""
    try:
        from weave.evaluation.eval_imperative import (  # type: ignore[import-not-found]
            EvaluationLogger,
        )
    except ModuleNotFoundError as e:
        raise ImportError(
            "`wandb.EvalTable` requires the `weave` package to be installed. "
            "Install it with `pip install weave`."
        ) from e

    if not hasattr(EvaluationLogger, "_create_with_meta"):
        raise ImportError(
            "`wandb.EvalTable` requires a version of weave whose "
            "EvaluationLogger has a `_create_with_meta` classmethod. "
            "Upgrade with `pip install -U weave`."
        )

    return EvaluationLogger


class EvalTable(Table):
    """A Table subclass that routes run.log() the new Eval Tables experience.

    When logged via run.log(), instead of uploading as a wandb artifact,
    upload as a Weave Eval via weave.EvaluationLogger.\
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
                as intput, output, or score will default to being output columns.
            score_columns: (List[str]) Names of the score columns.
                These represent derived scores for the outputs. By default, we will
                auto-summarize any numeric and boolean scores.

        Examples:
            et1 = wandb.EvalTable(
                input_columns=["image"],
                output_columns=["prediction"],
                score_columns=["score"],
                data=[pil_image, "4", 0.5]],
            )
            run.log({"my_eval_1": et1})
            # If you don't specify columns or dataframe, but specify input, output,
            # and score columns, we will infer the list of columns from the input,
            # output, and score columns, in that order.

            et3 = wandb.EvalTable(
                columns=["image", "prediction", "score"],
                input_columns=["image"],
                score_columns=["score"],
                data=[pil_image, "4", 0.5]],
            )
            run.log({"my_eval_2": et2})
            # If you do specify columns or dataframe, you can specify types for
            # those existing columns. Any unassigned column will be treated as an
            # output column (e.g. "prediction" in this case.)

            et3 = wandb.EvalTable(
                columns=["image", "prediction", "score"],
                data=[pil_image, "4", 0.5]],
            )
            run.log({"my_eval_3": et3})
            # If you don't assign any input columns, we will auto-inject a numeric
            # "row" index as the input column, and comparisons will match by row
            # index. All columns will be treated as outputs.

            et4 = wandb.EvalTable(
                input_columns=["image"],
                output_columns=["prediction"],
                score_columns=["score"],
                data=[pil_image, "4", 0.5]],
            )
            et.set_summary({"val_loss": 0.3})
            run.log({"my_eval_5": et5})
            # You can set eval-level attributes and summary scores.
        """
        # Fail fast if weave is missing or too old.
        _import_evaluation_logger()
        self._input_columns: list[str] = list(input_columns or [])
        self._output_columns: list[str] = list(output_columns or [])
        self._score_columns: list[str] = list(score_columns or [])
        self._summary: dict | None = None
        self._auto_summarize: bool = True
        # Persisted across `_log_to_weave` calls; created on first call,
        # reused on subsequent INCREMENTAL log calls so all batches land
        # in the same eval. None until first log.
        # Can't init now becaus we have to at least wait for bind_to_run.
        self._weave_eval_logger: Any = None
        self._last_weave_logged_idx: int | None = None
        self._is_incremental_finished = False

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

    def bind_to_run(  # type: ignore[override]
        self,
        run: LocalRun,
        key: str,
        step: int,
        id_: int | None = None,
        ignore_copy_err: bool | None = None,
    ) -> None:
        # Store context for to_json; skip the file-copy that Table.bind_to_run does.
        self._run = run
        self._key = key

    def to_json(self, run_or_artifact: Any) -> dict:
        if self._is_incremental_finished:
            raise UsageError("Cannot log an EvalTable after finish() has been called.")

        if isinstance(run_or_artifact, wandb.Artifact):
            raise TypeError("EvalTable cannot be logged to a wandb.Artifact.")
        if hasattr(run_or_artifact, "add") and not hasattr(run_or_artifact, "log"):
            raise TypeError("EvalTable cannot be logged to a wandb.Artifact.")

        # Run context: route to Weave EvaluationLogger.
        self._log_to_weave(run_or_artifact, self._key)

        return {
            "_type": "eval-table",
            "ncols": len(self.columns),
            "nrows": len(self.data),
            "log_mode": self.log_mode,
            "evaluate_call_id": (
                self._weave_eval_logger._evaluate_call.id
                if self._weave_eval_logger is not None
                else None
            ),
        }

    def _validate_columns(
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

    def _validate_no_nested_tables(self) -> None:
        """Raise if any cell value is a Table (or EvalTable) instance.

        Nested tables don't translate to weave's eval model and would either
        produce broken evals or silently lose information; reject upfront.
        """
        for row_idx, row in enumerate(self.data):
            for col_idx, val in enumerate(row):
                if isinstance(val, Table):
                    col = self.columns[col_idx]
                    raise TypeError(
                        f"Cell at row {row_idx}, column {col!r} contains a "
                        f"{type(val).__name__}; EvalTable does not support "
                        "nested Tables (or EvalTables) as cell values."
                    )

    def set_summary(
        self, summary: dict | None = None, auto_summarize: bool = True
    ) -> None:
        """Set the summary passed to EvaluationLogger.log_summary when logged."""
        self._summary = summary
        self._auto_summarize = auto_summarize

    def finish(self) -> None:
        """Finalize an INCREMENTAL EvalTable after all rows have been logged."""
        if self.log_mode != "INCREMENTAL":
            raise UsageError(
                "EvalTable.finish() is only supported for log_mode='INCREMENTAL'."
            )

        if self._is_incremental_finished:
            return

        ev = self._weave_eval_logger
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
            yield {col: unwrap_value(val, col, warned) for col, val in zip(cols, row)}

    def _setup_weave_eval_logger(self, run: Any, key: str) -> Any:
        """Build the EvaluationLogger on first call. Idempotent (returns the same logger)."""
        if self._weave_eval_logger is not None:
            return self._weave_eval_logger

        # Deferred import: wandb.integration.weave imports wandb at module level,
        # so a top-level import here would create a circular import.
        from wandb.integration.weave.weave import setup_with_import

        # Verify weave is installed AND new enough for EvalTable's needs before
        # attempting to use it. Catches both missing-install and version-skew
        # cases with a single, EvalTable-attributed error.
        eval_logger_cls = _import_evaluation_logger()

        if not setup_with_import(
            getattr(run, "entity", None), getattr(run, "project", None)
        ):
            raise RuntimeError(
                "Weave logging is disabled (WANDB_DISABLE_WEAVE is set). "
                "Unset it or use run.log() with a regular Table to suppress this."
            )

        self._validate_columns(
            self._input_columns, self._output_columns, self._score_columns
        )

        # Auto-generate a dataset based on input columns.
        dataset_rows: list[dict[str, Any]] | None = None
        if self._input_columns:
            dataset_rows = [
                {col: row[col] for col in self._input_columns}
                for row in self._iter_unwrapped_rows()
            ]

        self._weave_eval_logger = eval_logger_cls._create_with_meta(
            EVAL_TABLE_MARKER,
            name=key,
            dataset=dataset_rows,
        )

        # INCREMENTAL evals defer summary/finalization until `finish()` or
        # process exit. Register an atexit handler that fires before weave's
        # own EvaluationLogger cleanup: atexit runs in LIFO order, and weave
        # registered its `_cleanup_all_evaluations` at module import.
        if self.log_mode == "INCREMENTAL":
            atexit.register(self._summarize_at_exit)

        return self._weave_eval_logger

    def _summarize_at_exit(self) -> None:
        """Fire `log_summary` if this EvalTable has not been finished yet."""
        ev = self._weave_eval_logger
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
            return 0
        if self._last_weave_logged_idx is None:
            return len(self.data)
        return max(0, len(self.data) - self._last_weave_logged_idx - 1)

    def _log_to_weave(self, run: Any, key: str) -> None:
        if self._is_incremental_finished:
            raise UsageError("Cannot log an EvalTable after finish() has been called.")

        # IMMUTABLE: only the first run.log() should fire the weave path.
        # The framework may still call to_json on subsequent log()s, but
        # the eval has already been logged in full and summarized.
        if self.log_mode == "IMMUTABLE" and self._weave_eval_logger is not None:
            wandb.termwarn(
                "EvalTable with log_mode='IMMUTABLE' has already been logged. "
                "Subsequent run.log() calls have no effect. Set "
                "log_mode='MUTABLE' or log_mode='INCREMENTAL' to log updates.",
                repeat=False,
            )
            return

        # Validate cell values every call: rows can be added between log
        # calls, so a check confined to logger setup would miss later
        # additions in INCREMENTAL/MUTABLE mode.
        self._validate_no_nested_tables()

        # MUTABLE: each run.log() builds a brand-new eval. Finalize the
        # previous one (if any) and discard our reference so
        # `_setup_weave_eval_logger` builds a fresh logger below.
        if self.log_mode == "MUTABLE" and self._weave_eval_logger is not None:
            try:
                self._weave_eval_logger.log_summary(
                    self._summary, auto_summarize=self._auto_summarize
                )
            except Exception:
                pass  # Best-effort; don't block the new eval.
            self._weave_eval_logger = None

        ev = self._setup_weave_eval_logger(run, key)

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

        # INCREMENTAL: parent Table sets `_last_logged_idx` after each
        # `to_json`, so new rows start at _last_logged_idx + 1.
        # IMMUTABLE/MUTABLE: always log all rows (start_idx = 0); the
        # parent doesn't define _last_logged_idx for those modes, so the
        # getattr default handles it.
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
        # INCREMENTAL: log_summary fires from explicit `finish()` or via the
        # `_summarize_at_exit` atexit handler registered in `_setup_weave_eval_logger`,
        # using the latest `set_summary` value.
