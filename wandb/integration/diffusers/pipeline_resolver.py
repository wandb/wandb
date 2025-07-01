from typing import Any, Dict, Sequence

from wandb.sdk.integration_utils.auto_logging import Response

from .resolvers import (
    SUPPORTED_MULTIMODAL_PIPELINES,
    DiffusersMultiModalPipelineResolver,
)


class DiffusersPipelineResolver:
    """Resolver for `DiffusionPipeline` request and responses from [HuggingFace Diffusers](https://huggingface.co/docs/diffusers/index), providing necessary data transformations, formatting, and logging.

    This is based off `wandb.sdk.integration_utils.auto_logging.RequestResponseResolver`.
    """

    def __init__(self) -> None:
        self.wandb_table = None
        self.pipeline_call_count = 1

    def __call__(
        self,
        args: Sequence[Any],
        kwargs: Dict[str, Any],
        response: Response,
        start_time: float,
        time_elapsed: float,
    ) -> Any:
        """Main call method for the `DiffusersPipelineResolver` class.

        Args:
            args: (Sequence[Any]) List of arguments.
            kwargs: (Dict[str, Any]) Dictionary of keyword arguments.
            response: (wandb.sdk.integration_utils.auto_logging.Response) The response from
                the request.
            start_time: (float) Time when request started.
            time_elapsed: (float) Time elapsed for the request.

        Returns:
            Packed data as a dictionary for logging to wandb, None if an exception occurred.
        """
        pipeline_name = args[0].__class__.__name__
        resolver = None
        if pipeline_name in SUPPORTED_MULTIMODAL_PIPELINES:
            resolver = DiffusersMultiModalPipelineResolver(
                pipeline_name, self.pipeline_call_count
            )
            self.pipeline_call_count += 1
        loggable_dict = resolver(args, kwargs, response, start_time, time_elapsed)
        return loggable_dict
