from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Union

import torch
import wandb
from diffusers import DiffusionPipeline
from PIL import Image
from weave.monitoring import StreamTable

from ..utils import chunkify


class BaseDiffusersCallback(ABC):
    """Base callback for logging the results of a
    [`DiffusionPipeline`](https://github.com/huggingface/diffusers/blob/v0.21.0/src/diffusers/pipelines/pipeline_utils.py#L480)
    from [🧨 Diffusers](https://huggingface.co/docs/diffusers/index) to Weights & Biases.

    Arguments:
        pipeline: (diffusers.DiffusionPipeline) The `DiffusionPipeline` from
            `diffusers`.
        prompt (Union[str, List[str]]): The prompt or prompts to guide the image
            generation.
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
        wandb_project: str,
        wandb_entity: Optional[str] = None,
        weave_mode: bool = False,
        num_inference_steps: int = 50,
        num_images_per_prompt: Optional[int] = 1,
        negative_prompt: Optional[Union[str, List[str]]] = None,
        configs: Optional[Dict] = None,
        **kwargs,
    ) -> None:
        super().__init__()
        self.pipeline = pipeline
        self.prompt = prompt
        self.wandb_project = wandb_project
        self.wandb_entity = wandb_entity
        self.weave_mode = weave_mode
        self.num_inference_steps = num_inference_steps
        self.num_images_per_prompt = num_images_per_prompt
        self.negative_prompt = negative_prompt
        self.configs = configs
        self.wandb_table = None
        self.table_row = []
        self.starting_step = 1
        self.log_step = num_inference_steps
        self.job_type = "text-to-image"
        self.table_name = "Text-To-Image"
        self.initialize_wandb(wandb_project, wandb_entity)
        self.build_wandb_table()

    def update_configs(self) -> None:
        """Update the configs as a state of the callback. This function is called inside
        `initialize_wandb()`.
        """
        pipeline_configs = dict(self.pipeline.config)
        pipeline_configs["scheduler"] = list(pipeline_configs["scheduler"])
        pipeline_configs["scheduler"][1] = dict(self.pipeline.scheduler.config)
        additional_configs = {
            "prompt": self.prompt,
            "negative_prompt": self.negative_prompt
            if self.negative_prompt is not None
            else "",
            "num_inference_steps": self.num_inference_steps,
            "num_images_per_prompt": self.num_images_per_prompt,
            "pipeline": pipeline_configs,
        }
        self.configs = (
            {**self.configs, **additional_configs}
            if self.configs is not None
            else additional_configs
        )

    def initialize_wandb(self, wandb_project: str, wandb_entity: str) -> None:
        """Initializes the wandb run if not already initialized. If `weave_mode` is `True`,
        then a [StreamTable](https://docs.wandb.ai/guides/weave/streamtable) is initialized
        instead of a wandb run. This function is called automatically when the callback is
        initialized.

        Arguments:
            wandb_project (str): The name of the W&B project.
            wandb_entity (str): The name of the W&B entity.
        """
        self.update_configs()
        if self.weave_mode:
            if self.wandb_entity is None:
                wandb.termerror(
                    "The parameter wandb_entity must be provided when weave_mode is enabled."
                )
            else:
                self.stream_table = StreamTable(
                    f"{self.wandb_entity}/{self.wandb_project}/{self.table_name}"
                )
                self.table_row = []
        else:
            if wandb.run is None:
                if wandb_project is not None:
                    wandb.init(
                        project=wandb_project,
                        entity=wandb_entity,
                        job_type=self.job_type,
                        config=self.configs,
                    )
                else:
                    wandb.termerror("The parameter wandb_project must be provided.")

    def build_wandb_table(self) -> None:
        """Specifies the columns of the wandb table if not in weave mode. This function is
        called automatically when the callback is initialized.
        """
        self.table_columns = [
            "Prompt",
            "Negative-Prompt",
            "Generated-Image",
            "Image-Size",
        ]

    @abstractmethod
    def generate(self, latents: torch.FloatTensor) -> List:
        """Generate images from latents. This method must be implemented in the child class."""
        pass

    def populate_table_row(
        self, prompt: str, negative_prompt: str, image: Image
    ) -> None:
        """Populates the table row with the prompt, negative prompt, the generated image, and
        the configs.

        Arguments:
            prompt (str): The prompt to guide the image generation.
            negative_prompt (str): The prompt not to guide the image generation.
            image (Image): The generated image.
        """
        width, height = image.size
        if self.weave_mode:
            self.table_row += [
                {
                    "Generated-Image": image,
                    "Image-Size": {"Width": width, "Height": height},
                    "Configs": self.configs,
                }
            ]
        else:
            self.table_row = [
                prompt,
                negative_prompt if negative_prompt is not None else "",
                wandb.Image(image),
                {"Width": width, "Height": height},
            ]

    def at_initial_step(self):
        """A function that will be called at the initial step of the denoising loop during inference."""
        if not self.weave_mode:
            self.wandb_table = wandb.Table(columns=self.table_columns)

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
                        prompt_logging[idx], negative_prompt_logging[idx], image
                    )
                    if not self.weave_mode:
                        self.wandb_table.add_data(*self.table_row)
            if end_experiment:
                self.end_experiment()

    def end_experiment(self):
        """Ends the experiment. This function is called automatically at the end of
        `__call__` the parameter `end_experiment` is set to `True`.
        """
        if self.weave_mode:
            self.stream_table.log(self.table_row)
            self.stream_table.finish()
        elif wandb.run is not None:
            wandb.log({self.table_name: self.wandb_table})
            wandb.finish()
