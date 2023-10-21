from typing import Any, Dict, List, Optional, Union

import numpy as np
import torch
import wandb
from diffusers import DiffusionPipeline
from diffusers.image_processor import PipelineImageInput
from PIL import Image

from .base_callback import BaseDiffusersCallback
from ..utils import chunkify


class BaseImage2ImageCallback(BaseDiffusersCallback):
    """Base callback for logging the results of a
    [`DiffusionPipeline`](https://github.com/huggingface/diffusers/blob/v0.21.0/src/diffusers/pipelines/pipeline_utils.py#L480)
    from [🧨 Diffusers](https://huggingface.co/docs/diffusers/index)
    for logging the results of any image2image translation task to Weights & Biases.

    Arguments:
        pipeline: (diffusers.DiffusionPipeline) The `DiffusionPipeline` from
            `diffusers`.
        prompt: (Union[str, List[str]]) The prompt or prompts to guide the image
            generation.
        input_images: (PipelineImageInput) The input image, numpy array or tensor
            representing an image batch to be used as the starting point. For both numpy
            array and pytorch tensor, the expected value range is between [0, 1] If it's
            a tensor or a list or tensors, the expected shape should be `(B, C, H, W)`
            or `(C, H, W)`. If it is a numpy array or a list of arrays, the expected
            shape should be (B, H, W, C) or (H, W, C) It can also accept image latents as
            image, but if passing latents directly it is not encoded again.
        wandb_project: (Optional[str]) The name of the project where you're sending
            the new run. The project is not necessary to be specified unless the run
            has automatically been initiatlized before the callback is defined.
        wandb_entity: (Optional[str]) An entity is a username or team name where
            you're sending runs. This entity must exist before you can send runs there,
            so make sure to create your account or team in the UI before starting to
            log runs. If you don't specify an entity, the run will be sent to your
            default entity, which is usually your username. Change your default entity
            in [your settings](https://wandb.ai/settings) under "default location to
            create new projects".
        weave_mode: (bool) Whether to use log to a
            [weave board](https://docs.wandb.ai/guides/weave) instead of W&B dashboard or
            not. The weave mode logs the configs, generated images and timestamp in a
            [`StreamTable`](https://docs.wandb.ai/guides/weave/streamtable) instead of a
            `wandb.Table` and does not require a wandb run to be initialized in order to
            start logging. This makes it possible to log muliple generations without having
            to initialize or terminate runs. Note that the parameter `wandb_entity` must be
            explicitly specified in order to use weave mode.
        num_inference_steps: (int) The number of denoising steps. More denoising steps
            usually lead to a higher quality image at the expense of slower inference.
        num_images_per_prompt: (Optional[int]) The number of images to generate per
            prompt.
        negative_prompt: (Optional[Union[str, List[str]]]) The prompt or prompts not
            to guide the image generation. Ignored when not using guidance
            (i.e., ignored if `guidance_scale` is less than `1`).
        configs: (Optional[Dict]) Additional configs for the experiment you want to
            sync, for example, for example, `seed` could be a good config to be passed
            here.
    """

    def __init__(
        self,
        pipeline: DiffusionPipeline,
        prompt: Union[str, List[str]],
        input_images: PipelineImageInput,
        wandb_project: str,
        wandb_entity: Optional[str] = None,
        weave_mode: bool = False,
        num_inference_steps: int = 50,
        num_images_per_prompt: Optional[int] = 1,
        negative_prompt: Optional[Union[str, List[str]]] = None,
        configs: Optional[Dict] = None,
        **kwargs,
    ) -> None:
        self.job_type = "image-to-image"
        super().__init__(
            pipeline=pipeline,
            prompt=prompt,
            wandb_project=wandb_project,
            wandb_entity=wandb_entity,
            weave_mode=weave_mode,
            num_inference_steps=num_inference_steps,
            num_images_per_prompt=num_images_per_prompt,
            negative_prompt=negative_prompt,
            configs=configs,
            **kwargs,
        )
        self.input_images = self.postprocess_input_images(input_images)

    def initialize_wandb(self, wandb_project, wandb_entity) -> None:
        """Initializes the wandb run if not already initialized. If `weave_mode` is `True`,
        then a [StreamTable](https://docs.wandb.ai/guides/weave/streamtable) is initialized
        instead of a wandb run. This function is called automatically when the callback is
        initialized.

        Arguments:
            wandb_project (str): The name of the W&B project.
            wandb_entity (str): The name of the W&B entity.
        """
        self.job_type = "image-to-image"
        self.table_name = "Image-To-Image"
        super().initialize_wandb(wandb_project, wandb_entity)

    def postprocess_input_images(
        self, input_images: Union[torch.Tensor, Image.Image, np.array]
    ) -> Image.Image:
        """Postprocess input images to be logged to the W&B Table/StreamTable.

        Arguments:
            input_images (Union[torch.Tensor, Image.Image, np.array]): The input images
                to be postprocessed.
        """
        if isinstance(input_images, torch.Tensor):
            input_images = self.pipeline.image_processor.pt_to_numpy(input_images)
            input_images = self.pipeline.image_processor.numpy_to_pil(input_images)
        elif isinstance(input_images, Image.Image):
            input_images = [input_images]
        elif isinstance(input_images, np.array):
            input_images = self.pipeline.image_processor.numpy_to_pil(input_images)
        return input_images

    def build_wandb_table(self) -> None:
        """Specifies the columns of the wandb table if not in weave mode. This function is
        called automatically when the callback is initialized.
        """
        super().build_wandb_table()
        self.table_columns = ["Input-Image", "Input-Image-Size"] + self.table_columns

    def populate_table_row(
        self, input_image: Image.Image, prompt: str, negative_prompt: str, image: Any
    ) -> None:
        """Populates the table row with the input image, prompt, negative prompt, the
        generated image, and the configs.

        Arguments:
            input_image (Image): The input image.s
            prompt (str): The prompt to guide the image generation.
            negative_prompt (str): The prompt not to guide the image generation.
            image (Image): The generated image.
        """
        input_width, input_height = input_image.size
        generated_width, generated_height = image.size
        self.table_row = (
            {
                "Input-Image": input_image,
                "Input-Image-Size": {"Width": input_width, "Height": input_height},
                "Prompt": prompt,
                "Negative-Prompt": negative_prompt
                if negative_prompt is not None
                else "",
                "Generated-Image": image,
                "Generated-Image-Size": {
                    "Width": generated_width,
                    "Height": generated_height,
                },
                "Configs": self.configs,
            }
            if self.weave_mode
            else [
                wandb.Image(input_image),
                {"Width": input_width, "Height": input_height},
                prompt,
                negative_prompt if negative_prompt is not None else "",
                wandb.Image(image),
                {"Width": generated_width, "Height": generated_height},
            ]
        )

    def __call__(
        self,
        step: int,
        timestep: int,
        latents: torch.FloatTensor,
        end_experiment: bool = True,
    ):
        """A function that will be called every `callback_steps` steps during
        inference with the `diffusers.DiffusionPipeline`.

        Arguments:
            step (int): The current step of the inference.
            timestep (int): The current timestep of the inference.
            latents (torch.FloatTensor): The latent tensor used to generate the image.
            end_experiment (bool): Whether to end the experiment automatically or not
                after the pipeline is executed.
        """
        if step == self.starting_step:
            self.at_initial_step()
        if step == self.log_step:
            images = self.generate(latents)
            prompt_logging = (
                self.prompt if isinstance(self.prompt, list) else [self.prompt]
            )
            negative_prompt_logging = (
                self.negative_prompt
                if isinstance(self.negative_prompt, list)
                else [self.negative_prompt] * len(prompt_logging)
            )
            images = chunkify(images, len(prompt_logging))
            for idx in range(len(prompt_logging)):
                for image in images[idx]:
                    self.populate_table_row(
                        self.input_images[0],
                        prompt_logging[idx],
                        negative_prompt_logging[idx],
                        image,
                    )
                    if self.weave_mode:
                        self.stream_table.log(self.table_row)
                    else:
                        self.wandb_table.add_data(*self.table_row)
            if end_experiment:
                self.end_experiment()
