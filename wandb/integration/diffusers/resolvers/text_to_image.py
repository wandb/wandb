import logging
import inspect
from typing import Any, Dict, Sequence

import wandb
from wandb.sdk.integration_utils.auto_logging import Response
from .utils import chunkify, get_updated_kwargs


logger = logging.getLogger(__name__)


SUPPORTED_TEXT_TO_IMAGE_PIPELINES = {
    "StableDiffusionPipeline": {
        "table-schema": ["Prompt", "Negative-Prompt", "Generated-Image"],
        "kwarg-logging": ["prompt", "negative_prompt"],
    },
    "KandinskyCombinedPipeline": {
        "table-schema": ["Prompt", "Negative-Prompt", "Generated-Image"],
        "kwarg-logging": ["prompt", "negative_prompt"],
    },
    "KandinskyV22CombinedPipeline": {
        "table-schema": ["Prompt", "Negative-Prompt", "Generated-Image"],
        "kwarg-logging": ["prompt", "negative_prompt"],
    },
    "LatentConsistencyModelPipeline": {
        "table-schema": ["Prompt", "Generated-Image"],
        "kwarg-logging": ["prompt"],
    },
    "LDMTextToImagePipeline": {
        "table-schema": ["Prompt", "Generated-Image"],
        "kwarg-logging": ["prompt"],
    },
    "StableDiffusionPanoramaPipeline": {
        "table-schema": ["Prompt", "Negative-Prompt", "Generated-Image"],
        "kwarg-logging": ["prompt", "negative_prompt"],
    },
    "PixArtAlphaPipeline": {
        "table-schema": ["Prompt", "Negative-Prompt", "Generated-Image"],
        "kwarg-logging": ["prompt", "negative_prompt"],
    },
    "StableDiffusionSAGPipeline": {
        "table-schema": ["Prompt", "Negative-Prompt", "Generated-Image"],
        "kwarg-logging": ["prompt", "negative_prompt"],
    },
    "SemanticStableDiffusionPipeline": {
        "table-schema": ["Prompt", "Negative-Prompt", "Generated-Image"],
        "kwarg-logging": ["prompt", "negative_prompt"],
    },
    "WuerstchenCombinedPipeline": {
        "table-schema": ["Prompt", "Negative-Prompt", "Generated-Image"],
        "kwarg-logging": ["prompt", "negative_prompt"],
    },
    "IFPipeline": {
        "table-schema": ["Prompt", "Negative-Prompt", "Generated-Image"],
        "kwarg-logging": ["prompt", "negative_prompt"],
    },
    "AltDiffusionPipeline": {
        "table-schema": ["Prompt", "Negative-Prompt", "Generated-Image"],
        "kwarg-logging": ["prompt", "negative_prompt"],
    },
}


class DiffusersTextToImagePipelineResolver:
    def __init__(self, pipeline_name: str) -> None:
        self.pipeline_name = pipeline_name
        columns = []
        if pipeline_name in SUPPORTED_TEXT_TO_IMAGE_PIPELINES:
            columns += SUPPORTED_TEXT_TO_IMAGE_PIPELINES[pipeline_name]["table-schema"]
        self.wandb_table = wandb.Table(columns=columns)

    def __call__(
        self,
        args: Sequence[Any],
        kwargs: Dict[str, Any],
        response: Response,
        start_time: float,
        time_elapsed: float,
    ) -> Any:
        try:
            # Get the pipeline and the args
            pipeline, args = args[0], args[1:]

            # Update the Kwargs so that they can be logged easily
            kwargs = get_updated_kwargs(pipeline, args, kwargs)

            # Get the pipeline configs
            pipeline_configs = dict(pipeline.config)
            pipeline_configs["pipeline-name"] = self.pipeline_name

            wandb.config.update(
                {"workflow": {"pipeline": pipeline_configs, "params": kwargs}}
            )

            # Return the WandB loggable dict
            loggable_dict = self.prepare_loggable_dict(response, kwargs)
            return loggable_dict
        except Exception as e:
            print(e)
        return None

    def prepare_loggable_dict(
        self, response: Response, kwargs: Dict[str, Any]
    ) -> Dict[str, Any]:
        images = response.images
        loggable_kwarg_ids = SUPPORTED_TEXT_TO_IMAGE_PIPELINES[self.pipeline_name][
            "kwarg-logging"
        ]
        loggable_kwarg_chunks = []
        for loggable_kwarg_id in loggable_kwarg_ids:
            loggable_kwarg_chunks.append(
                kwargs[loggable_kwarg_id]
                if isinstance(kwargs[loggable_kwarg_id], list)
                else [kwargs[loggable_kwarg_id]]
            )
        images = chunkify(images, len(loggable_kwarg_chunks[0]))
        for idx in range(len(loggable_kwarg_chunks[0])):
            for image in images[idx]:
                wandb.log(
                    {
                        "Generated-Image": wandb.Image(
                            image, caption=loggable_kwarg_chunks[0][idx]
                        )
                    }
                )
                table_row = [
                    loggable_kwarg_chunk[idx]
                    for loggable_kwarg_chunk in loggable_kwarg_chunks
                ]
                table_row = [val if val is not None else "" for val in table_row]
                table_row.append(wandb.Image(image))
                self.wandb_table.add_data(*table_row)
        return {"text-to-image": self.wandb_table}
