import logging
from typing import Any, Dict, List, Sequence

import wandb
from wandb.sdk.integration_utils.auto_logging import Response

from .utils import (
    chunkify,
    decode_sdxl_t2i_latents,
    get_updated_kwargs,
    postprocess_np_arrays_for_video,
    postprocess_pils_to_np,
)

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
    "AnimateDiffPipeline": {
        "table-schema": [
            "Prompt",
            "Negative-Prompt",
            "Number-of-Frames",
            "Generated-Video",
        ],
        "kwarg-logging": ["prompt", "negative_prompt", "num_frames"],
        "kwarg-actions": [None, None, None],
        "output-type": "video",
    },
    "StableVideoDiffusionPipeline": {
        "table-schema": [
            "Input-Image",
            "Frames-Per-Second",
            "Generated-Video",
        ],
        "kwarg-logging": ["image", "fps"],
        "kwarg-actions": [wandb.Image, None],
        "output-type": "video",
    },
    "AudioLDMPipeline": {
        "table-schema": [
            "Prompt",
            "Negative-Prompt",
            "Audio-Length-in-Seconds",
            "Generated-Audio",
        ],
        "kwarg-logging": ["prompt", "negative_prompt", "audio_length_in_s"],
        "kwarg-actions": [None, None, None],
        "output-type": "audio",
    },
    "AudioLDM2Pipeline": {
        "table-schema": [
            "Prompt",
            "Negative-Prompt",
            "Audio-Length-in-Seconds",
            "Generated-Audio",
        ],
        "kwarg-logging": ["prompt", "negative_prompt", "audio_length_in_s"],
        "kwarg-actions": [None, None, None],
        "output-type": "audio",
    },
    "MusicLDMPipeline": {
        "table-schema": [
            "Prompt",
            "Negative-Prompt",
            "Audio-Length-in-Seconds",
            "Generated-Audio",
        ],
        "kwarg-logging": ["prompt", "negative_prompt", "audio_length_in_s"],
        "kwarg-actions": [None, None, None],
        "output-type": "audio",
    },
    "StableDiffusionPix2PixZeroPipeline": {
        "table-schema": [
            "Prompt",
            "Negative-Prompt",
            "Generated-Image",
        ],
        "kwarg-logging": ["prompt", "negative_prompt"],
        "kwarg-actions": [None, None],
    },
    "PNDMPipeline": {
        "table-schema": [
            "Batch-Size",
            "Number-of-Inference-Steps",
            "Generated-Image",
        ],
        "kwarg-logging": ["batch_size", "num_inference_steps"],
        "kwarg-actions": [None, None],
    },
    "ShapEPipeline": {
        "table-schema": [
            "Prompt",
            "Generated-Video",
        ],
        "kwarg-logging": ["prompt"],
        "kwarg-actions": [None],
        "output-type": "video",
    },
    "StableDiffusionImg2ImgPipeline": {
        "table-schema": [
            "Source-Image",
            "Prompt",
            "Negative-Prompt",
            "Generated-Image",
        ],
        "kwarg-logging": ["image", "prompt", "negative_prompt"],
        "kwarg-actions": [wandb.Image, None, None],
    },
    "StableDiffusionInpaintPipeline": {
        "table-schema": [
            "Source-Image",
            "Mask-Image",
            "Prompt",
            "Negative-Prompt",
            "Generated-Image",
        ],
        "kwarg-logging": ["image", "mask_image", "prompt", "negative_prompt"],
        "kwarg-actions": [wandb.Image, wandb.Image, None, None],
    },
    "StableDiffusionDepth2ImgPipeline": {
        "table-schema": [
            "Source-Image",
            "Prompt",
            "Negative-Prompt",
            "Generated-Image",
        ],
        "kwarg-logging": ["image", "prompt", "negative_prompt"],
        "kwarg-actions": [wandb.Image, None, None],
    },
    "StableDiffusionImageVariationPipeline": {
        "table-schema": [
            "Source-Image",
            "Generated-Image",
        ],
        "kwarg-logging": [
            "image",
        ],
        "kwarg-actions": [wandb.Image],
    },
    "StableDiffusionPipelineSafe": {
        "table-schema": [
            "Prompt",
            "Negative-Prompt",
            "Generated-Image",
        ],
        "kwarg-logging": ["prompt", "negative_prompt"],
        "kwarg-actions": [None, None],
    },
    "StableDiffusionUpscalePipeline": {
        "table-schema": [
            "Source-Image",
            "Prompt",
            "Negative-Prompt",
            "Upscaled-Image",
        ],
        "kwarg-logging": ["image", "prompt", "negative_prompt"],
        "kwarg-actions": [wandb.Image, None, None],
    },
    "StableDiffusionAdapterPipeline": {
        "table-schema": [
            "Source-Image",
            "Prompt",
            "Negative-Prompt",
            "Generated-Image",
        ],
        "kwarg-logging": ["image", "prompt", "negative_prompt"],
        "kwarg-actions": [wandb.Image, None, None],
    },
    "StableDiffusionGLIGENPipeline": {
        "table-schema": [
            "Prompt",
            "GLIGEN-Phrases",
            "GLIGEN-Boxes",
            "GLIGEN-Inpaint-Image",
            "Negative-Prompt",
            "Generated-Image",
        ],
        "kwarg-logging": [
            "prompt",
            "gligen_phrases",
            "gligen_boxes",
            "gligen_inpaint_image",
            "negative_prompt",
        ],
        "kwarg-actions": [None, None, None, wandb.Image, None],
    },
    "VersatileDiffusionTextToImagePipeline": {
        "table-schema": [
            "Prompt",
            "Negative-Prompt",
            "Generated-Image",
        ],
        "kwarg-logging": ["prompt", "negative_prompt"],
        "kwarg-actions": [None, None],
    },
    "VersatileDiffusionImageVariationPipeline": {
        "table-schema": [
            "Source-Image",
            "Negative-Prompt",
            "Generated-Image",
        ],
        "kwarg-logging": ["image", "negative_prompt"],
        "kwarg-actions": [wandb.Image, None],
    },
    "VersatileDiffusionDualGuidedPipeline": {
        "table-schema": [
            "Source-Image",
            "Prompt",
            "Negative-Prompt",
            "Generated-Image",
        ],
        "kwarg-logging": ["image", "prompt", "negative_prompt"],
        "kwarg-actions": [wandb.Image, None, None],
    },
    "LDMPipeline": {
        "table-schema": [
            "Batch-Size",
            "Number-of-Inference-Steps",
            "Generated-Image",
        ],
        "kwarg-logging": ["batch_size", "num_inference_steps"],
        "kwarg-actions": [None, None],
    },
    "TextToVideoSDPipeline": {
        "table-schema": [
            "Prompt",
            "Negative-Prompt",
            "Number-of-Frames",
            "Generated-Video",
        ],
        "kwarg-logging": ["prompt", "negative_prompt", "num_frames"],
        "output-type": "video",
    },
    "TextToVideoZeroPipeline": {
        "table-schema": [
            "Prompt",
            "Negative-Prompt",
            "Number-of-Frames",
            "Generated-Video",
        ],
        "kwarg-logging": ["prompt", "negative_prompt", "video_length"],
    },
    "AmusedPipeline": {
        "table-schema": [
            "Prompt",
            "Guidance Scale",
            "Generated-Image",
        ],
        "kwarg-logging": [
            "prompt",
            "guidance_scale",
        ],
        "kwarg-actions": [None, None],
    },
    "StableDiffusionXLControlNetPipeline": {
        "table-schema": [
            "Prompt-1",
            "Prompt-2",
            "Control-Image",
            "Negative-Prompt-1",
            "Negative-Prompt-2",
            "Generated-Image",
        ],
        "kwarg-logging": [
            "prompt",
            "prompt_2",
            "image",
            "negative_prompt",
            "negative_prompt_2",
        ],
        "kwarg-actions": [None, None, wandb.Image, None, None],
    },
    "StableDiffusionXLControlNetImg2ImgPipeline": {
        "table-schema": [
            "Prompt-1",
            "Prompt-2",
            "Input-Image",
            "Control-Image",
            "Negative-Prompt-1",
            "Negative-Prompt-2",
            "Generated-Image",
        ],
        "kwarg-logging": [
            "prompt",
            "prompt_2",
            "image",
            "control_image",
            "negative_prompt",
            "negative_prompt_2",
        ],
        "kwarg-actions": [None, None, wandb.Image, wandb.Image, None, None],
    },
    "Kandinsky3Pipeline": {
        "table-schema": [
            "Prompt",
            "Negative-Prompt",
            "Generated-Image",
        ],
        "kwarg-logging": [
            "prompt",
            "negative_prompt",
        ],
        "kwarg-actions": [None, None],
    },
    "Kandinsky3Img2ImgPipeline": {
        "table-schema": [
            "Prompt",
            "Negative-Prompt",
            "Input-Image",
            "Generated-Image",
        ],
        "kwarg-logging": [
            "prompt",
            "negative_prompt",
            "image",
        ],
        "kwarg-actions": [None, None, wandb.Image],
    },
    "StableDiffusionXLPipeline": {
        "table-schema": [
            "Prompt",
            "Negative-Prompt",
            "Prompt-2",
            "Negative-Prompt-2",
            "Generated-Image",
        ],
        "kwarg-logging": [
            "prompt",
            "negative_prompt",
            "prompt_2",
            "negative_prompt_2",
        ],
        "kwarg-actions": [None, None, None, None],
    },
    "StableDiffusionXLImg2ImgPipeline": {
        "table-schema": [
            "Prompt",
            "Negative-Prompt",
            "Prompt-2",
            "Negative-Prompt-2",
            "Input-Image",
            "Generated-Image",
        ],
        "kwarg-logging": [
            "prompt",
            "negative_prompt",
            "prompt_2",
            "negative_prompt_2",
            "image",
        ],
        "kwarg-actions": [None, None, None, None, wandb.Image],
    },
}


class DiffusersMultiModalPipelineResolver:
    """Resolver for  request and responses from [HuggingFace Diffusers](https://huggingface.co/docs/diffusers/index) multi-modal Diffusion Pipelines, providing necessary data transformations, formatting, and logging.

    This resolver is internally involved in the
    `__call__` for `wandb.integration.diffusers.pipeline_resolver.DiffusersPipelineResolver`.
    This is based on `wandb.sdk.integration_utils.auto_logging.RequestResponseResolver`.

    Arguments:
        pipeline_name: (str) The name of the Diffusion Pipeline.
    """

    def __init__(self, pipeline_name: str, pipeline_call_count: int) -> None:
        self.pipeline_name = pipeline_name
        self.pipeline_call_count = pipeline_call_count
        columns = []
        if pipeline_name in SUPPORTED_MULTIMODAL_PIPELINES:
            columns += SUPPORTED_MULTIMODAL_PIPELINES[pipeline_name]["table-schema"]
        else:
            wandb.Error("Pipeline not supported for logging")
        self.wandb_table = wandb.Table(columns=columns)

    def __call__(
        self,
        args: Sequence[Any],
        kwargs: Dict[str, Any],
        response: Response,
        start_time: float,
        time_elapsed: float,
    ) -> Any:
        """Main call method for the `DiffusersPipelineResolver` class.

        Arguments:
            args: (Sequence[Any]) List of arguments.
            kwargs: (Dict[str, Any]) Dictionary of keyword arguments.
            response: (wandb.sdk.integration_utils.auto_logging.Response) The response from
                the request.
            start_time: (float) Time when request started.
            time_elapsed: (float) Time elapsed for the request.

        Returns:
            Packed data as a dictionary for logging to wandb, None if an exception occurred.
        """
        try:
            # Get the pipeline and the args
            pipeline, args = args[0], args[1:]

            # Update the Kwargs so that they can be logged easily
            kwargs = get_updated_kwargs(pipeline, args, kwargs)

            # Get the pipeline configs
            pipeline_configs = dict(pipeline.config)
            pipeline_configs["pipeline-name"] = self.pipeline_name

            if "workflow" not in wandb.config:
                wandb.config.update(
                    {
                        "workflow": [
                            {
                                "pipeline": pipeline_configs,
                                "params": kwargs,
                                "stage": f"Pipeline-Call-{self.pipeline_call_count}",
                            }
                        ]
                    }
                )
            else:
                existing_workflow = wandb.config.workflow
                updated_workflow = existing_workflow + [
                    {
                        "pipeline": pipeline_configs,
                        "params": kwargs,
                        "stage": f"Pipeline-Call-{self.pipeline_call_count}",
                    }
                ]
                wandb.config.update(
                    {"workflow": updated_workflow}, allow_val_change=True
                )

            # Return the WandB loggable dict
            loggable_dict = self.prepare_loggable_dict(pipeline, response, kwargs)
            return loggable_dict
        except Exception as e:
            logger.warning(e)
        return None

    def get_output_images(self, response: Response) -> List:
        """Unpack the generated images, audio, video, etc. from the Diffusion Pipeline's response.

        Arguments:
            response: (wandb.sdk.integration_utils.auto_logging.Response) The response from
                the request.

        Returns:
            List of generated images, audio, video, etc.
        """
        if "output-type" not in SUPPORTED_MULTIMODAL_PIPELINES[self.pipeline_name]:
            return response.images
        else:
            if (
                SUPPORTED_MULTIMODAL_PIPELINES[self.pipeline_name]["output-type"]
                == "video"
            ):
                if self.pipeline_name in ["ShapEPipeline"]:
                    return response.images
                return response.frames
            elif (
                SUPPORTED_MULTIMODAL_PIPELINES[self.pipeline_name]["output-type"]
                == "audio"
            ):
                return response.audios

    def log_media(self, image: Any, loggable_kwarg_chunks: List, idx: int) -> None:
        """Log the generated images, audio, video, etc. from the Diffusion Pipeline's response along with an optional caption to a media panel in the run.

        Arguments:
            image: (Any) The generated images, audio, video, etc. from the Diffusion
                Pipeline's response.
            loggable_kwarg_chunks: (List) Loggable chunks of kwargs.
        """
        if "output-type" not in SUPPORTED_MULTIMODAL_PIPELINES[self.pipeline_name]:
            try:
                caption = ""
                if self.pipeline_name in [
                    "StableDiffusionXLPipeline",
                    "StableDiffusionXLImg2ImgPipeline",
                ]:
                    prompt_index = SUPPORTED_MULTIMODAL_PIPELINES[self.pipeline_name][
                        "kwarg-logging"
                    ].index("prompt")
                    prompt2_index = SUPPORTED_MULTIMODAL_PIPELINES[self.pipeline_name][
                        "kwarg-logging"
                    ].index("prompt_2")
                    caption = f"Prompt-1: {loggable_kwarg_chunks[prompt_index][idx]}\nPrompt-2: {loggable_kwarg_chunks[prompt2_index][idx]}"
                else:
                    prompt_index = SUPPORTED_MULTIMODAL_PIPELINES[self.pipeline_name][
                        "kwarg-logging"
                    ].index("prompt")
                    caption = loggable_kwarg_chunks[prompt_index][idx]
            except ValueError:
                caption = None
            wandb.log(
                {
                    f"Generated-Image/Pipeline-Call-{self.pipeline_call_count}": wandb.Image(
                        image, caption=caption
                    )
                }
            )
        else:
            if (
                SUPPORTED_MULTIMODAL_PIPELINES[self.pipeline_name]["output-type"]
                == "video"
            ):
                try:
                    prompt_index = SUPPORTED_MULTIMODAL_PIPELINES[self.pipeline_name][
                        "kwarg-logging"
                    ].index("prompt")
                    caption = loggable_kwarg_chunks[prompt_index][idx]
                except ValueError:
                    caption = None
                wandb.log(
                    {
                        f"Generated-Video/Pipeline-Call-{self.pipeline_call_count}": wandb.Video(
                            postprocess_pils_to_np(image), fps=4, caption=caption
                        )
                    }
                )
            elif (
                SUPPORTED_MULTIMODAL_PIPELINES[self.pipeline_name]["output-type"]
                == "audio"
            ):
                try:
                    prompt_index = SUPPORTED_MULTIMODAL_PIPELINES[self.pipeline_name][
                        "kwarg-logging"
                    ].index("prompt")
                    caption = loggable_kwarg_chunks[prompt_index][idx]
                except ValueError:
                    caption = None
                wandb.log(
                    {
                        f"Generated-Audio/Pipeline-Call-{self.pipeline_call_count}": wandb.Audio(
                            image, sample_rate=16000, caption=caption
                        )
                    }
                )

    def add_data_to_table(
        self, image: Any, loggable_kwarg_chunks: List, idx: int
    ) -> None:
        """Populate the row of the `wandb.Table`.

        Arguments:
            image: (Any) The generated images, audio, video, etc. from the Diffusion
                Pipeline's response.
            loggable_kwarg_chunks: (List) Loggable chunks of kwargs.
            idx: (int) Chunk index.
        """
        table_row = []
        kwarg_actions = SUPPORTED_MULTIMODAL_PIPELINES[self.pipeline_name][
            "kwarg-actions"
        ]
        for column_idx, loggable_kwarg_chunk in enumerate(loggable_kwarg_chunks):
            if kwarg_actions[column_idx] is None:
                table_row.append(
                    loggable_kwarg_chunk[idx]
                    if loggable_kwarg_chunk[idx] is not None
                    else ""
                )
            else:
                table_row.append(kwarg_actions[column_idx](loggable_kwarg_chunk[idx]))
        if "output-type" not in SUPPORTED_MULTIMODAL_PIPELINES[self.pipeline_name]:
            table_row.append(wandb.Image(image))
        else:
            if (
                SUPPORTED_MULTIMODAL_PIPELINES[self.pipeline_name]["output-type"]
                == "video"
            ):
                table_row.append(wandb.Video(postprocess_pils_to_np(image), fps=4))
            elif (
                SUPPORTED_MULTIMODAL_PIPELINES[self.pipeline_name]["output-type"]
                == "audio"
            ):
                table_row.append(wandb.Audio(image, sample_rate=16000))
        self.wandb_table.add_data(*table_row)

    def prepare_loggable_dict(
        self, pipeline: Any, response: Response, kwargs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Prepare the loggable dictionary, which is the packed data as a dictionary for logging to wandb, None if an exception occurred.

        Arguments:
            pipeline: (Any) The Diffusion Pipeline.
            response: (wandb.sdk.integration_utils.auto_logging.Response) The response from
                the request.
            kwargs: (Dict[str, Any]) Dictionary of keyword arguments.

        Returns:
            Packed data as a dictionary for logging to wandb, None if an exception occurred.
        """
        # Unpack the generated images, audio, video, etc. from the Diffusion Pipeline's response.
        images = self.get_output_images(response)
        if (
            self.pipeline_name == "StableDiffusionXLPipeline"
            and kwargs["output_type"] == "latent"
        ):
            images = decode_sdxl_t2i_latents(pipeline, response.images)

        # Account for exception pipelines for text-to-video
        if self.pipeline_name in ["TextToVideoSDPipeline", "TextToVideoZeroPipeline"]:
            video = postprocess_np_arrays_for_video(
                images, normalize=self.pipeline_name == "TextToVideoZeroPipeline"
            )
            wandb.log(
                {
                    f"Generated-Video/Pipeline-Call-{self.pipeline_call_count}": wandb.Video(
                        video, fps=4, caption=kwargs["prompt"]
                    )
                }
            )
            loggable_kwarg_ids = SUPPORTED_MULTIMODAL_PIPELINES[self.pipeline_name][
                "kwarg-logging"
            ]
            table_row = [
                kwargs[loggable_kwarg_ids[idx]]
                for idx in range(len(loggable_kwarg_ids))
            ]
            table_row.append(wandb.Video(video, fps=4))
            self.wandb_table.add_data(*table_row)
        else:
            loggable_kwarg_ids = SUPPORTED_MULTIMODAL_PIPELINES[self.pipeline_name][
                "kwarg-logging"
            ]
            # chunkify loggable kwargs
            loggable_kwarg_chunks = []
            for loggable_kwarg_id in loggable_kwarg_ids:
                loggable_kwarg_chunks.append(
                    kwargs[loggable_kwarg_id]
                    if isinstance(kwargs[loggable_kwarg_id], list)
                    else [kwargs[loggable_kwarg_id]]
                )
            # chunkify the generated media
            images = chunkify(images, len(loggable_kwarg_chunks[0]))
            for idx in range(len(loggable_kwarg_chunks[0])):
                for image in images[idx]:
                    # Log media to media panel
                    self.log_media(image, loggable_kwarg_chunks, idx)
                    # Populate the row of the wandb_table
                    self.add_data_to_table(image, loggable_kwarg_chunks, idx)
        return {
            f"Result-Table/Pipeline-Call-{self.pipeline_call_count}": self.wandb_table
        }
