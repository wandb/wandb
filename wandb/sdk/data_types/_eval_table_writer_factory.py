from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from wandb.errors import UsageError
from wandb.sdk.data_types._eval_table_writer import (
    EvalTableWriter,
    UnsupportedMediaMode,
)
from wandb.sdk.data_types._eval_table_writer_ces import CESEvalTableWriter
from wandb.sdk.data_types._eval_table_writer_weave import WeaveEvalTableWriter

EvalTableBackend = Literal["weave", "ces"]


if TYPE_CHECKING:
    from wandb.sdk.wandb_run import Run as LocalRun


def create_eval_table_writer(
    backend: EvalTableBackend,
    *,
    allow_mixed_types: bool,
    unsupported_media_mode: UnsupportedMediaMode,
) -> EvalTableWriter:
    if backend == "weave":
        return WeaveEvalTableWriter(
            unsupported_media_mode=unsupported_media_mode,
        )
    if backend == "ces":
        if allow_mixed_types:
            raise UsageError("CES EvalTable logging requires allow_mixed_types=False.")
        return CESEvalTableWriter(
            unsupported_media_mode=unsupported_media_mode,
        )
    raise UsageError(
        f"Unsupported EvalTable backend {backend!r}; expected 'weave' or 'ces'."
    )


def create_default_eval_table_writer(
    run: LocalRun,
    *,
    allow_mixed_types: bool,
    unsupported_media_mode: UnsupportedMediaMode,
) -> EvalTableWriter:
    """Create the default writer after a run is available."""
    # The default is always Weave for now. Keeping selection at bind time lets
    # it later depend on capabilities advertised for this run.
    return create_eval_table_writer(
        "weave",
        allow_mixed_types=allow_mixed_types,
        unsupported_media_mode=unsupported_media_mode,
    )
