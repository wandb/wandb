from typing import Any, Dict, Sequence

from wandb.sdk.integration_utils.auto_logging import Response

from .resolvers.text_to_image import (
    SUPPORTED_TEXT_TO_IMAGE_PIPELINES,
    DiffusersTextToImagePipelineResolver,
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
        if pipeline_name in SUPPORTED_TEXT_TO_IMAGE_PIPELINES:
            return DiffusersTextToImagePipelineResolver(pipeline_name)(
                args, kwargs, response, start_time, time_elapsed
            )
