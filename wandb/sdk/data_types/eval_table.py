from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, cast

from typing_extensions import override

import wandb
import wandb.integration.weave as weave_integration
from wandb.errors import UsageError
from wandb.sdk.data_types.table import Table

if TYPE_CHECKING:
    from wandb.sdk.wandb_run import Run as LocalRun


_MIN_WEAVE_VERSION = "0.52.41"
_EVAL_TABLE_WEAVE_INSTALL_HINT = 'Install it with `pip install wandb["eval-table"]`.'
_EVAL_TABLE_WEAVE_DEP_MSG = (
    f"`wandb.EvalTable` is missing weave dependency. {_EVAL_TABLE_WEAVE_INSTALL_HINT}"
)


def _ensure_weave_version() -> None:
    try:
        weave = weave_integration.import_weave()
    except ImportError as e:
        raise ImportError(_EVAL_TABLE_WEAVE_DEP_MSG) from e

    try:
        weave_integration.check_weave_version(weave, _MIN_WEAVE_VERSION)
    except ImportError as e:
        raise ImportError(
            f"`wandb.EvalTable` requires {e}. {_EVAL_TABLE_WEAVE_INSTALL_HINT}"
        ) from e


def _init_weave_for_run(run: LocalRun) -> None:
    try:
        if not weave_integration.init_weave(run.entity, run.project):
            raise RuntimeError(
                "Weave logging is disabled (WANDB_DISABLE_WEAVE is set). "
                "Unset it or use run.log() with a regular Table to suppress this."
            )
    except ImportError as e:
        raise ImportError(_EVAL_TABLE_WEAVE_DEP_MSG) from e
    except ValueError as e:
        # init_weave raises ValueError when the W&B run has no project, or when
        # Weave is already initialized for a different entity/project.
        raise UsageError(str(e)) from e


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
        columns=None,
        data=None,
        rows=None,
        dataframe=None,
        dtype=None,
        optional=True,
        allow_mixed_types=False,
        log_mode: Literal["IMMUTABLE"] = "IMMUTABLE",
    ) -> None:
        """Initializes an EvalTable object.

        TODO: Incomplete stub. Missing bulk of implementation.
        """
        if log_mode != "IMMUTABLE":
            raise UsageError("EvalTable currently only supports log_mode='IMMUTABLE'.")

        _ensure_weave_version()

        # TODO: Add column mapping support

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
        # Now that we have run context, initialize/validate Weave for this project.
        # Skip the file-copy that Table.bind_to_run does.
        _init_weave_for_run(run)
        self._run = run
        self._run_log_key = str(key)

    @override
    def to_json(self, run_or_artifact: Any) -> dict:
        """Returns the JSON representation expected by the backend.

        TODO: Incomplete stub. Missing bulk of implementation.

        <!-- lazydoc-ignore: internal -->
        """
        if isinstance(run_or_artifact, wandb.Artifact):
            raise TypeError("EvalTable cannot be logged to a wandb.Artifact.")

        run = cast("LocalRun", run_or_artifact)

        # TODO: Remove when weave adds support for offline mode
        if run.offline:
            raise UsageError(
                "EvalTable does not support offline mode yet. "
                "Use wandb.init(mode='online') or unset WANDB_MODE."
            )

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

    def _create_weave_eval_logger(self) -> Any:
        from weave.evaluation.eval_imperative import EvaluationLogger

        # TODO: In a later PR, create an EvaluationLogger and log rows to Weave.
        _ = EvaluationLogger
        raise UsageError("EvalTable logging is not implemented yet.")

    def _log_to_weave(self) -> str:
        ev = self._create_weave_eval_logger()
        return ev._evaluate_call.id
