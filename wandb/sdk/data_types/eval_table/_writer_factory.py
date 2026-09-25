from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from wandb.apis.public.service_api import ServiceApi
from wandb.errors import UsageError
from wandb.proto import wandb_internal_pb2 as pb
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


def require_eval_table_server_feature(run: LocalRun) -> None:
    """Return a service API after verifying that the server supports EvalTables."""
    service_api = ServiceApi(run._settings)
    if not service_api.feature_enabled(pb.ServerFeature.EVAL_TABLES_CES):
        raise UsageError("This W&B server does not support EvalTable logging.")
