import logging

from wandb.sdk.integration_utils.auto_logging import AutologAPI

from .resolver import HuggingFacePipelineRequestResponseResolver

logger = logging.getLogger(__name__)

autolog = AutologAPI(
    name="transformers",
    symbols=("Pipeline.__call__",),
    resolver=HuggingFacePipelineRequestResponseResolver(),
    # telemetry_feature="transformers_autolog", #TODO: Add telemetry
)
