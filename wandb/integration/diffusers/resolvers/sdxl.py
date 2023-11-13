import logging
import inspect
from typing import Any, Dict, Sequence

import wandb
from wandb.sdk.integration_utils.auto_logging import Response
from .utils import chunkify, get_updated_kwargs


SUPPORTED_SDXL_PIPELINES = [
    "StableDiffusionXLPipeline",
    "StableDiffusionXLImg2ImgPipeline",
]

TEXT_TO_IMAGE_COLUMNS = [
    "Workflow-Stage",
    "Prompt",
    "Negative-Prompt",
    "Prompt-2",
    "Negative-Prompt-2",
    "Generated-Image",
]


class SDXLResolver:
    def __init__(self, pipeline_name: str) -> None:
        self.pipeline_name = pipeline_name
        self.wandb_table = None
        self.task = None
        self.workflow_stage = None

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

            if "workflow" not in wandb.config:
                wandb.config.update(
                    {"workflow": [{"pipeline": pipeline_configs, "params": kwargs}]}
                )
            else:
                existing_workflow = wandb.config.workflow
                updated_workflow = existing_workflow + [
                    {"pipeline": pipeline_configs, "params": kwargs}
                ]
                wandb.config.workflow.update(updated_workflow)

            # Return the WandB loggable dict
            loggable_dict = self.prepare_loggable_dict(
                pipeline_configs, response, kwargs
            )
            return loggable_dict
        except Exception as e:
            print(e)
        return None

    def create_wandb_table(self, pipeline_configs: Dict[str, Any]) -> None:
        columns = []
        if self.pipeline_name == "StableDiffusionXLPipeline":
            columns += TEXT_TO_IMAGE_COLUMNS
            self.task = "text_to_image"
            self.workflow_stage = "Base"
        elif self.pipeline_name == "StableDiffusionXLImg2ImgPipeline":
            if (
                pipeline_configs["_name_or_path"]
                == "stabilityai/stable-diffusion-xl-refiner-1.0"
            ):
                columns += TEXT_TO_IMAGE_COLUMNS
                self.task = "text_to_image"
                self.workflow_stage = "Refiner"
        self.wandb_table = wandb.Table(columns=columns)

    def prepare_loggable_dict_for_text_to_image(
        self, workflow_stage: str, response: Response, kwargs: Dict[str, Any]
    ) -> Dict[str, Any]:
        prompt_logging = (
            kwargs["prompt"]
            if isinstance(kwargs["prompt"], list)
            else [kwargs["prompt"]]
        )
        prompt2_logging = (
            kwargs["prompt_2"]
            if isinstance(kwargs["prompt_2"], list)
            else [kwargs["prompt_2"]]
        )
        negative_prompt_logging = (
            kwargs["negative_prompt"]
            if isinstance(kwargs["negative_prompt"], list)
            else [kwargs["negative_prompt"]]
        )
        negative_prompt2_logging = (
            kwargs["negative_prompt_2"]
            if isinstance(kwargs["negative_prompt_2"], list)
            else [kwargs["negative_prompt_2"]]
        )
        images = chunkify(response.images, len(prompt_logging))
        for idx in range(len(prompt_logging)):
            for image in images[idx]:
                wandb.log(
                    {
                        "Generated-Image": wandb.Image(
                            image,
                            caption=f"Prompt-1: {prompt_logging[idx]}\nPrompt-2: {prompt2_logging[idx]}",
                        )
                    }
                )
                self.wandb_table.add_data(
                    workflow_stage,
                    prompt_logging[idx] if prompt_logging[idx] is not None else "",
                    negative_prompt_logging[idx]
                    if negative_prompt_logging[idx] is not None
                    else "",
                    prompt2_logging[idx] if prompt2_logging[idx] is not None else "",
                    negative_prompt2_logging[idx]
                    if negative_prompt2_logging[idx] is not None
                    else "",
                    wandb.Image(image),
                )

    def prepare_loggable_dict(
        self,
        pipeline_configs: Dict[str, Any],
        response: Response,
        kwargs: Dict[str, Any],
    ):
        self.create_wandb_table(pipeline_configs)
        if self.task == "text_to_image":
            self.prepare_loggable_dict_for_text_to_image(
                self.workflow_stage, response, kwargs
            )
        return {"text-to-image": self.wandb_table}
