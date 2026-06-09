from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, Literal

from typing_extensions import override

import wandb
import wandb.integration.weave as weave_integration
from wandb.errors import UsageError
from wandb.sdk.data_types.table import Table

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

    from wandb.sdk.wandb_run import Run as LocalRun


_MIN_WEAVE_VERSION = "0.52.41"


class EvalTable(Table):
    """A Table subclass that routes run.log() to the new Eval Tables experience.

    When logged via run.log(), an EvalTable is logged as a Weave Eval via
    weave.EvaluationLogger instead of being uploaded as a regular wandb Table
    artifact.

    TODO: Incomplete stub. Missing bulk of implementation.

    <!-- lazydoc-ignore-class: internal -->
    """

    _log_type = "eval-table"

    def __init__(
        self,
        columns: list[str | int] | None = None,
        data: list[Iterable[Any]] | np.ndarray | pd.DataFrame | None = None,
        rows: list[Iterable[Any]] | None = None,
        dataframe: pd.DataFrame | None = None,
        dtype: Any = None,
        optional: bool | list[bool] = True,
        allow_mixed_types: bool = False,
        log_mode: Literal["IMMUTABLE"] = "IMMUTABLE",
        *,
        input_columns: list[str] | None = None,
        output_columns: list[str] | None = None,
        score_columns: list[str] | None = None,
    ) -> None:
        """Initializes an EvalTable object.

        TODO: Incomplete stub. Missing bulk of implementation.
        """
        if log_mode != "IMMUTABLE":
            raise UsageError("EvalTable currently only supports log_mode='IMMUTABLE'.")

        weave_integration.ensure_version(
            _MIN_WEAVE_VERSION,
            'EvalTable dependency error. Fix with: `pip install wandb["eval-table"]`.',
        )

        # TODO: Add column mapping support

        self._input_columns = list(input_columns or [])
        self._output_columns = list(output_columns or [])
        self._score_columns = list(score_columns or [])
        self._summary: dict | None = None
        self._auto_summarize: bool = True
        self._run_log_key: str | None = None

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

        TODO: Incomplete stub. Missing bulk of implementation.

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

        evaluate_call_id = self._log_to_weave()

        json_dict = {
            "_type": "eval-table",
            "ncols": len(self.columns),
            "nrows": len(self.data),
            "log_mode": self.log_mode,
            "evaluate_call_id": evaluate_call_id,
        }
        return json_dict

    def set_summary(
        self, summary: dict | None = None, auto_summarize: bool = True
    ) -> None:
        """Sets key/value pairs to be logged at the eval level.

        Args:
            auto_summarize: If true (default), auto-generate summaries for all score columns.
        """
        self._summary = summary
        self._auto_summarize = auto_summarize

    def _create_weave_eval_logger(self) -> Any:
        from weave.evaluation.eval_imperative import EvaluationLogger

        # TODO: In a later PR, create an EvaluationLogger and log rows to Weave.
        _ = EvaluationLogger
        raise NotImplementedError("EvalTable logging is not implemented yet.")

    def _log_to_weave(self) -> str:
        ev = self._create_weave_eval_logger()
        return ev._evaluate_call.id
