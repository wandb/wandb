from __future__ import annotations

from typing import Literal

from wandb.errors import UsageError
from wandb.sdk.data_types.eval_table._writer import EvalTableWriter
from wandb.sdk.data_types.eval_table._writer_ces import CESWriter
from wandb.sdk.data_types.eval_table._writer_weave import WeaveWriter

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
