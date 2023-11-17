from typing import Any, Dict, Sequence

from wandb.sdk.integration_utils.auto_logging import Response

from .resolvers import (
    SUPPORTED_SDXL_PIPELINES,
    SUPPORTED_MULTIMODAL_PIPELINES,
    SDXLResolver,
    DiffusersMultiModalPipelineResolver,
)


class DiffusersPipelineResolver:
    def __init__(self) -> None:
        self.wandb_table = None

    def __call__(
        self,
        args: Sequence[Any],
        kwargs: Dict[str, Any],
        response: Response,
        start_time: float,
        time_elapsed: float,
    ) -> Any:
        pipeline_name = args[0].__class__.__name__
        resolver = None
        if pipeline_name in SUPPORTED_MULTIMODAL_PIPELINES:
            resolver = DiffusersMultiModalPipelineResolver(pipeline_name)
        elif pipeline_name in SUPPORTED_SDXL_PIPELINES:
            resolver = SDXLResolver(pipeline_name)
        loggable_dict = resolver(args, kwargs, response, start_time, time_elapsed)
        return loggable_dict
