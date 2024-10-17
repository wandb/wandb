import logging

from .diffusers_autolog_api import DiffusersAutologAPI
from .pipeline_resolver import DiffusersPipelineResolver

logger = logging.getLogger(__name__)


resolver = DiffusersPipelineResolver()
symbols = [key + ".__call__" for key in resolver.supported_pipelines.keys()]

autolog = DiffusersAutologAPI(
    name="diffusers",
    symbols=symbols,
    resolver=resolver,
    telemetry_feature="diffusers_autolog",
)
