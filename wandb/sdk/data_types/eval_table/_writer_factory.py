from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from wandb.errors import UsageError
from wandb.sdk.data_types.eval_table._writer_weave import WeaveWriter
from wandb.sdk.data_types.eval_table._writer import EvalTableWriter

if TYPE_CHECKING:
    from wandb.sdk.wandb_run import Run as LocalRun

Backend = Literal["weave"]


def create_writer(
    backend: Backend,
    *,
    unsupported_media_mode: str,
) -> EvalTableWriter:
    if backend == "weave":
        return WeaveWriter(
            unsupported_media_mode=unsupported_media_mode,
        )
    raise UsageError(f"Unsupported EvalTable backend {backend!r}; expected 'weave'.")


def create_default_writer(
    run: LocalRun,
    *,
    unsupported_media_mode: str,
) -> EvalTableWriter:
    """Create the default writer after a run is available."""
    # The default is always Weave for now. Keeping selection at bind time lets
    # it later depend on capabilities advertised for this run.
    return create_writer(
        "weave",
        unsupported_media_mode=unsupported_media_mode,
    )
