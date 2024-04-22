import logging

from wandb.sdk.integration_utils.auto_logging import AutologAPI

from .pipeline_resolver import DiffusersPipelineResolver

logger = logging.getLogger(__name__)

resolver = DiffusersPipelineResolver()
symbols = [key + ".__call__" for key in resolver.supported_pipelines.keys()]

autolog = AutologAPI(
    name="diffusers",
    symbols=tuple(symbols),
    resolver=resolver,
    telemetry_feature="diffusers_autolog",
)
