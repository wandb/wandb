from __future__ import annotations

from typing import Literal

import wandb.integration.weave.media_adapters as media_adapters
from wandb.errors import UsageError
from wandb.sdk.data_types._eval_table_writer import EvalTableWriter
from wandb.sdk.data_types._eval_table_writer_ces import CESEvalTableWriter
from wandb.sdk.data_types._eval_table_writer_weave import WeaveEvalTableWriter

EvalTableBackend = Literal["weave", "ces"]


def create_eval_table_writer(
    backend: EvalTableBackend,
    *,
    allow_mixed_types: bool,
    unsupported_media_mode: media_adapters.UnsupportedMediaMode,
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
