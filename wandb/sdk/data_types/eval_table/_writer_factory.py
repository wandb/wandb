from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from wandb.errors import UsageError
from wandb.sdk.data_types.eval_table._writer import EvalTableWriter
from wandb.sdk.data_types.eval_table._writer_ces import CESWriter
from wandb.sdk.data_types.eval_table._writer_weave import WeaveWriter

if TYPE_CHECKING:
    from wandb.sdk.wandb_run import Run as LocalRun

Backend = Literal["weave", "ces"]


def create_writer(
    backend: Backend,
    *,
    allow_mixed_types: bool,
    unsupported_media_mode: str,
) -> EvalTableWriter:
    if backend == "weave":
        return WeaveWriter(
            unsupported_media_mode=unsupported_media_mode,
        )
    if backend == "ces":
        if allow_mixed_types:
            raise UsageError("CES EvalTable logging requires allow_mixed_types=False.")
        return CESWriter(
            unsupported_media_mode=unsupported_media_mode,
        )
    raise UsageError(
        f"Unsupported EvalTable backend {backend!r}; expected 'weave' or 'ces'."
    )


def create_default_writer(
    run: LocalRun,
    *,
    allow_mixed_types: bool,
    unsupported_media_mode: str,
) -> EvalTableWriter:
    """Create the default writer after a run is available."""
    # The default is always Weave for now. Keeping selection at bind time lets
    # it later depend on capabilities advertised for this run.
    return create_writer(
        "weave",
        allow_mixed_types=allow_mixed_types,
        unsupported_media_mode=unsupported_media_mode,
    )
