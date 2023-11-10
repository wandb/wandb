import logging

from wandb.sdk.integration_utils.auto_logging import AutologAPI

from .resolver import DiffusersTextToImagePipelineResolver

logger = logging.getLogger(__name__)

text_to_image_autolog = AutologAPI(
    name="diffusers",
    symbols=(
        "DiffusionPipeline.__call__",
        "StableDiffusionPipeline.__call__",
    ),
    resolver=DiffusersTextToImagePipelineResolver(),
)
