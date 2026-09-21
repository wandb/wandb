from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from wandb.apis.public.service_api import ServiceApi
from wandb.errors import UsageError
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.data_types.eval_table._writer import Writer
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
    service_api: ServiceApi | None = None,
) -> Writer:
    if backend == "weave":
        return WeaveWriter(
            unsupported_media_mode=unsupported_media_mode,
        )
    if backend == "ces":
        if allow_mixed_types:
            raise UsageError("CES EvalTable logging requires allow_mixed_types=False.")
        return CESWriter(
            service_api=service_api,
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
) -> Writer:
    """Create the writer advertised as the default by the bound run's server."""
    service_api = ServiceApi(run._settings)
    backend: Backend = (
        "ces"
        if service_api.feature_enabled(pb.ServerFeature.EVAL_TABLES_CES)
        else "weave"
    )
    return create_writer(
        backend,
        allow_mixed_types=allow_mixed_types,
        unsupported_media_mode=unsupported_media_mode,
        service_api=service_api,
    )
