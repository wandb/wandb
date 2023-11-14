import logging
from typing import Any, Dict, List, Sequence

import wandb
from wandb.sdk.integration_utils.auto_logging import Response
from .utils import chunkify, get_updated_kwargs


logger = logging.getLogger(__name__)


SUPPORTED_MULTIMODAL_PIPELINES = {
    "BlipDiffusionPipeline": {
        "table-schema": [
            "Reference-Image",
            "Prompt",
            "Negative-Prompt",
            "Source-Subject-Category",
            "Target-Subject-Category",
            "Generated-Image",
        ],
        "kwarg-logging": [
            "reference_image",
            "prompt",
            "neg_prompt",
            "source_subject_category",
            "target_subject_category",
        ],
        "kwarg-actions": [wandb.Image, None, None, None, None],
    },
    "BlipDiffusionControlNetPipeline": {
        "table-schema": [
            "Reference-Image",
            "Control-Image",
            "Prompt",
            "Negative-Prompt",
            "Source-Subject-Category",
            "Target-Subject-Category",
            "Generated-Image",
        ],
        "kwarg-logging": [
            "reference_image",
            "condtioning_image",
            "prompt",
            "neg_prompt",
            "source_subject_category",
            "target_subject_category",
        ],
        "kwarg-actions": [wandb.Image, wandb.Image, None, None, None, None],
    },
    "StableDiffusionControlNetPipeline": {
        "table-schema": [
            "Control-Image",
            "Prompt",
            "Negative-Prompt",
            "Generated-Image",
        ],
        "kwarg-logging": ["image", "prompt", "negative_prompt"],
        "kwarg-actions": [wandb.Image, None, None],
    },
    "StableDiffusionControlNetImg2ImgPipeline": {
        "table-schema": [
            "Source-Image",
            "Control-Image",
            "Prompt",
            "Negative-Prompt",
            "Generated-Image",
        ],
        "kwarg-logging": ["image", "control_image", "prompt", "negative_prompt"],
        "kwarg-actions": [wandb.Image, wandb.Image, None, None],
    },
    "StableDiffusionControlNetInpaintPipeline": {
        "table-schema": [
            "Source-Image",
            "Mask-Image",
            "Control-Image",
            "Prompt",
            "Negative-Prompt",
            "Generated-Image",
        ],
        "kwarg-logging": [
            "image",
            "mask_image",
            "control_image",
            "prompt",
            "negative_prompt",
        ],
        "kwarg-actions": [wandb.Image, wandb.Image, wandb.Image, None, None],
    },
    "CycleDiffusionPipeline": {
        "table-schema": [
            "Source-Image",
            "Prompt",
            "Source-Prompt",
            "Generated-Image",
        ],
        "kwarg-logging": [
            "image",
            "prompt",
            "source_prompt",
        ],
        "kwarg-actions": [wandb.Image, None, None],
    },
    "StableDiffusionInstructPix2PixPipeline": {
        "table-schema": [
            "Source-Image",
            "Prompt",
            "Negative-Prompt",
            "Generated-Image",
        ],
        "kwarg-logging": [
            "image",
            "prompt",
            "negative_prompt",
        ],
        "kwarg-actions": [wandb.Image, None, None],
    },
    "PaintByExamplePipeline": {
        "table-schema": [
            "Source-Image",
            "Example-Image",
            "Mask-Prompt",
            "Generated-Image",
        ],
        "kwarg-logging": [
            "image",
            "example_image",
            "mask_image",
        ],
        "kwarg-actions": [wandb.Image, wandb.Image, wandb.Image],
    },
    "RePaintPipeline": {
        "table-schema": [
            "Source-Image",
            "Mask-Prompt",
            "Generated-Image",
        ],
        "kwarg-logging": [
            "image",
            "mask_image",
        ],
        "kwarg-actions": [wandb.Image, wandb.Image],
    },
    "StableDiffusionPipeline": {
        "table-schema": ["Prompt", "Negative-Prompt", "Generated-Image"],
        "kwarg-logging": ["prompt", "negative_prompt"],
        "kwarg-actions": [None, None],
    },
    "KandinskyCombinedPipeline": {
        "table-schema": ["Prompt", "Negative-Prompt", "Generated-Image"],
        "kwarg-logging": ["prompt", "negative_prompt"],
        "kwarg-actions": [None, None],
    },
    "KandinskyV22CombinedPipeline": {
        "table-schema": ["Prompt", "Negative-Prompt", "Generated-Image"],
        "kwarg-logging": ["prompt", "negative_prompt"],
        "kwarg-actions": [None, None],
    },
    "LatentConsistencyModelPipeline": {
        "table-schema": ["Prompt", "Generated-Image"],
        "kwarg-logging": ["prompt"],
        "kwarg-actions": [None],
    },
    "LDMTextToImagePipeline": {
        "table-schema": ["Prompt", "Generated-Image"],
        "kwarg-logging": ["prompt"],
        "kwarg-actions": [None],
    },
    "StableDiffusionPanoramaPipeline": {
        "table-schema": ["Prompt", "Negative-Prompt", "Generated-Image"],
        "kwarg-logging": ["prompt", "negative_prompt"],
        "kwarg-actions": [None, None],
    },
    "PixArtAlphaPipeline": {
        "table-schema": ["Prompt", "Negative-Prompt", "Generated-Image"],
        "kwarg-logging": ["prompt", "negative_prompt"],
        "kwarg-actions": [None, None],
    },
    "StableDiffusionSAGPipeline": {
        "table-schema": ["Prompt", "Negative-Prompt", "Generated-Image"],
        "kwarg-logging": ["prompt", "negative_prompt"],
        "kwarg-actions": [None, None],
    },
    "SemanticStableDiffusionPipeline": {
        "table-schema": ["Prompt", "Negative-Prompt", "Generated-Image"],
        "kwarg-logging": ["prompt", "negative_prompt"],
        "kwarg-actions": [None, None],
    },
    "WuerstchenCombinedPipeline": {
        "table-schema": ["Prompt", "Negative-Prompt", "Generated-Image"],
        "kwarg-logging": ["prompt", "negative_prompt"],
        "kwarg-actions": [None, None],
    },
    "IFPipeline": {
        "table-schema": ["Prompt", "Negative-Prompt", "Generated-Image"],
        "kwarg-logging": ["prompt", "negative_prompt"],
        "kwarg-actions": [None, None],
    },
    "AltDiffusionPipeline": {
        "table-schema": ["Prompt", "Negative-Prompt", "Generated-Image"],
        "kwarg-logging": ["prompt", "negative_prompt"],
        "kwarg-actions": [None, None],
    },
    "StableDiffusionAttendAndExcitePipeline": {
        "table-schema": ["Prompt", "Negative-Prompt", "Generated-Image"],
        "kwarg-logging": ["prompt", "negative_prompt"],
        "kwarg-actions": [None, None],
    },
    "KandinskyImg2ImgCombinedPipeline": {
        "table-schema": [
            "Source-Image",
            "Prompt",
            "Negative-Prompt",
            "Generated-Image",
        ],
        "kwarg-logging": ["image", "prompt", "negative_prompt"],
        "kwarg-actions": [wandb.Image, None, None],
    },
    "KandinskyInpaintCombinedPipeline": {
        "table-schema": [
            "Source-Image",
            "Prompt",
            "Negative-Prompt",
            "Generated-Image",
        ],
        "kwarg-logging": ["image", "prompt", "negative_prompt"],
        "kwarg-actions": [wandb.Image, None, None],
    },
    "KandinskyV22Img2ImgCombinedPipeline": {
        "table-schema": [
            "Source-Image",
            "Prompt",
            "Negative-Prompt",
            "Generated-Image",
        ],
        "kwarg-logging": ["image", "prompt", "negative_prompt"],
        "kwarg-actions": [wandb.Image, None, None],
    },
    "KandinskyV22InpaintCombinedPipeline": {
        "table-schema": [
            "Source-Image",
            "Prompt",
            "Negative-Prompt",
            "Generated-Image",
        ],
        "kwarg-logging": ["image", "prompt", "negative_prompt"],
        "kwarg-actions": [wandb.Image, None, None],
    },
}


class DiffusersMultiModalPipelineResolver:
    def __init__(self, pipeline_name: str) -> None:
        self.pipeline_name = pipeline_name
        columns = []
        if pipeline_name in SUPPORTED_MULTIMODAL_PIPELINES:
            columns += SUPPORTED_MULTIMODAL_PIPELINES[pipeline_name]["table-schema"]
        self.wandb_table = wandb.Table(columns=columns)

    def __call__(
        self,
        args: Sequence[Any],
        kwargs: Dict[str, Any],
        response: Response,
        start_time: float,
        time_elapsed: float,
    ) -> Any:
        # try:
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
        # except Exception as e:
        #     print(e)
        # return None
    
    def log_media(self, image: Any, loggable_kwarg_chunks: List, idx: int) -> None:
        if "output-type" not in SUPPORTED_MULTIMODAL_PIPELINES[self.pipeline_name]:
            try:
                prompt_index = SUPPORTED_MULTIMODAL_PIPELINES[self.pipeline_name][
                    "kwarg-logging"
                ].index("prompt")
                caption = loggable_kwarg_chunks[prompt_index][idx]
            except ValueError:
                caption = None
            wandb.log({"Generated-Image": wandb.Image(image, caption=caption)})
    
    def add_data_to_table(self, image: Any, loggable_kwarg_chunks: List, idx: int) -> None:
        table_row = []
        kwarg_actions = SUPPORTED_MULTIMODAL_PIPELINES[self.pipeline_name][
            "kwarg-actions"
        ]
        for column_idx, loggable_kwarg_chunk in enumerate(
            loggable_kwarg_chunks
        ):
            if kwarg_actions[column_idx] is None:
                table_row.append(
                    loggable_kwarg_chunk[idx]
                    if loggable_kwarg_chunk[idx] is not None
                    else ""
                )
            else:
                table_row.append(
                    kwarg_actions[column_idx](loggable_kwarg_chunk[idx])
                )
        if "output-type" not in SUPPORTED_MULTIMODAL_PIPELINES[self.pipeline_name]:
            table_row.append(wandb.Image(image))
        self.wandb_table.add_data(*table_row)

    def prepare_loggable_dict(
        self, response: Response, kwargs: Dict[str, Any]
    ) -> Dict[str, Any]:
        images = response.images
        loggable_kwarg_ids = SUPPORTED_MULTIMODAL_PIPELINES[self.pipeline_name][
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
                self.log_media(image, loggable_kwarg_chunks, idx)
                self.add_data_to_table(image, loggable_kwarg_chunks, idx)
        return {"Result-Table": self.wandb_table}
