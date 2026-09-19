from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from wandb.errors import UsageError
from wandb.sdk.data_types._eval_table_writer import EvalTableWriter
from wandb.sdk.data_types._eval_table_writer_weave import WeaveEvalTableWriter

if TYPE_CHECKING:
    from wandb.sdk.wandb_run import Run as LocalRun

EvalTableBackend = Literal["weave"]


def create_eval_table_writer(
    backend: EvalTableBackend,
    *,
    unsupported_media_mode: str,
) -> EvalTableWriter:
    if backend == "weave":
        return WeaveEvalTableWriter(
            unsupported_media_mode=unsupported_media_mode,
        )
    raise UsageError(f"Unsupported EvalTable backend {backend!r}; expected 'weave'.")


def create_default_eval_table_writer(
    run: LocalRun,
    *,
    unsupported_media_mode: str,
) -> EvalTableWriter:
    """Create the default writer after a run is available."""
    # The default is always Weave for now. Keeping selection at bind time lets
    # it later depend on capabilities advertised for this run.
    return create_eval_table_writer(
        "weave",
        unsupported_media_mode=unsupported_media_mode,
    )
