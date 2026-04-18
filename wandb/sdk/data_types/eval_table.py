"""EvalTable: a Table subclass that logs to Weave's EvaluationLogger via run.log()."""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any

from wandb.sdk.data_types.table import Table

if TYPE_CHECKING:
    from wandb.sdk.wandb_run import Run as LocalRun


class EvalTable(Table):
    """A Table subclass that routes run.log() to Weave's EvaluationLogger.

    Instead of uploading as an artifact, when logged via run.log(), each row
    becomes a call to EvaluationLogger.log_example(). Columns must be tagged
    as inputs, outputs, or scores.

    Example::

        table = wandb.EvalTable(
            columns=["question", "answer", "score"],
            data=[["What is 2+2?", "4", 1.0]],
            input_columns=["question"],
            output_columns=["answer"],
            score_columns=["score"],
        )
        run.log({"my_eval": table})
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
        log_mode="IMMUTABLE",
        *,
        input_columns: list[str] | None = None,
        output_columns: list[str] | None = None,
        score_columns: list[str] | None = None,
    ) -> None:
        self._input_columns: list[str] = list(input_columns or [])
        self._output_columns: list[str] = list(output_columns or [])
        self._score_columns: list[str] = list(score_columns or [])

        # Derive columns from role lists if columns arg omitted
        if columns is None and (
            self._input_columns or self._output_columns or self._score_columns
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
        # Artifact context: behave as a normal Table.
        # Weave logging does NOT fire in this path.
        try:
            import wandb

            if isinstance(run_or_artifact, wandb.Artifact):
                return super().to_json(run_or_artifact)
        except Exception:
            pass

        # Fallback artifact detection via duck-typing (no wandb.Artifact available)
        if hasattr(run_or_artifact, "add") and not hasattr(run_or_artifact, "log"):
            return super().to_json(run_or_artifact)

        # Run context: route to Weave EvaluationLogger.
        self._log_to_weave(run_or_artifact, self._key)
        return {"_type": "eval-table"}

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

        unassigned = table_cols - all_assigned
        if unassigned:
            warnings.warn(
                f"Column(s) {sorted(unassigned)} are not assigned to input_columns, "
                "output_columns, or score_columns and will be ignored during Weave logging.",
                stacklevel=3,
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

    def _log_to_weave(self, run: Any, key: str) -> None:
        # Deferred import: wandb.integration.weave imports wandb at module level,
        # so a top-level import here would create a circular import.
        from wandb.integration.weave.weave import setup_with_import

        if not setup_with_import(
            getattr(run, "entity", None), getattr(run, "project", None)
        ):
            raise RuntimeError(
                "Weave logging is disabled (WANDB_DISABLE_WEAVE is set). "
                "Unset it or use run.log() with a regular Table to suppress this."
            )

        from weave.evaluation.eval_imperative import (  # type: ignore[import-not-found]
            EvaluationLogger,
        )

        if not hasattr(EvaluationLogger, "log_batch"):
            raise AttributeError(
                "This version of weave's EvaluationLogger does not have log_batch(). "
                "Upgrade weave to a version that supports EvalTable logging."
            )

        self._validate_columns(
            self._input_columns, self._output_columns, self._score_columns
        )

        ev = EvaluationLogger(name=key)
        ev.log_batch(
            self,
            input_columns=self._input_columns,
            output_columns=self._output_columns,
            score_columns=self._score_columns,
        )
        ev.log_summary()
