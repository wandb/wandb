import logging

from wandb.sdk.integration_utils.auto_logging import AutologAPI

from .resolver import DiffusersPipelineResolver

logger = logging.getLogger(__name__)

resolver = DiffusersPipelineResolver()

autolog = AutologAPI(
    name="diffusers",
    symbols=("DiffusionPipeline.__call__",),
    resolver=resolver,
    telemetry_feature="diffusers_pipeline_autolog",
)

autolog.get_latest_id = resolver.get_latest_id
