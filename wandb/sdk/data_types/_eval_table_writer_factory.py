from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import wandb.integration.weave.media_adapters as media_adapters
from wandb.apis.public.service_api import ServiceApi
from wandb.errors import UsageError
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.data_types._eval_table_writer import EvalTableWriter
from wandb.sdk.data_types._eval_table_writer_ces import CESEvalTableWriter
from wandb.sdk.data_types._eval_table_writer_weave import WeaveEvalTableWriter

if TYPE_CHECKING:
    from wandb.sdk.wandb_run import Run as LocalRun


EvalTableBackend = Literal["weave", "ces"]


def create_eval_table_writer(
    backend: EvalTableBackend,
    *,
    allow_mixed_types: bool,
    unsupported_media_mode: media_adapters.UnsupportedMediaMode,
    service_api: ServiceApi | None = None,
) -> EvalTableWriter:
    if backend == "weave":
        return WeaveEvalTableWriter(
            unsupported_media_mode=unsupported_media_mode,
        )
    if backend == "ces":
        if allow_mixed_types:
            raise UsageError("CES EvalTable logging requires allow_mixed_types=False.")
        return CESEvalTableWriter(
            service_api=service_api,
            unsupported_media_mode=unsupported_media_mode,
        )
    raise UsageError(
        f"Unsupported EvalTable backend {backend!r}; expected 'weave' or 'ces'."
    )


def create_default_eval_table_writer(
    run: LocalRun,
    *,
    allow_mixed_types: bool,
    unsupported_media_mode: media_adapters.UnsupportedMediaMode,
) -> EvalTableWriter:
    """Create the writer advertised as the default by the bound run's server."""
    service_api = ServiceApi(run._settings)
    backend: EvalTableBackend = (
        "ces"
        if service_api.feature_enabled(pb.ServerFeature.EVAL_TABLES_CES)
        else "weave"
    )
    return create_eval_table_writer(
        backend,
        allow_mixed_types=allow_mixed_types,
        unsupported_media_mode=unsupported_media_mode,
        service_api=service_api,
    )
