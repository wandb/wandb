import logging

from wandb.sdk.integration_utils.auto_logging import AutologAPI

from .resolver import HuggingFacePipelineRequestResponseResolver

logger = logging.getLogger(__name__)

resolver = HuggingFacePipelineRequestResponseResolver()

autolog = AutologAPI(
    name="transformers",
    symbols=("Pipeline.__call__",),
    resolver=resolver,
    telemetry_feature="hf_pipeline_autolog",
)

autolog.get_latest_id = resolver.get_latest_id
