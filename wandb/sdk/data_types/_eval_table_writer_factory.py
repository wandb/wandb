from __future__ import annotations

from typing import Literal

import wandb.integration.weave.media_adapters as media_adapters
from wandb.errors import UsageError
from wandb.sdk.data_types._eval_table_writer import EvalTableWriter
from wandb.sdk.data_types._eval_table_writer_weave import WeaveEvalTableWriter

EvalTableBackend = Literal["weave"]


def create_eval_table_writer(
    backend: EvalTableBackend,
    *,
    unsupported_media_mode: media_adapters.UnsupportedMediaMode,
) -> EvalTableWriter:
    if backend == "weave":
        return WeaveEvalTableWriter(
            unsupported_media_mode=unsupported_media_mode,
        )
    raise UsageError(f"Unsupported EvalTable backend {backend!r}; expected 'weave'.")
