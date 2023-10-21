from typing import Dict, List, Optional, Union

import torch
from diffusers import DiffusionPipeline, KandinskyCombinedPipeline, KandinskyPipeline

from ..base import BaseDiffusersCallback


class KandinskyCallback(BaseDiffusersCallback):
    """Callback for [🧨 Diffusers](https://huggingface.co/docs/diffusers/index) logging
    the results of a
    [`KandinskyCombinedPipeline`](https://huggingface.co/docs/diffusers/api/pipelines/kandinsky#diffusers.KandinskyCombinedPipeline)
    generation to Weights & Biases.

    !!! note "Features:"
        - The callback automatically logs basic configs like prompt, negative prompt,
            etc. along with the generated image in a
            [`wandb.Table`](https://docs.wandb.ai/guides/tables).
        - The callback also logs configs for both the experiment as well as pipelines
            with the wandb run.
        - No need to initialize a run, the callback automatically initialized and ends
            runs gracefully.

    !!! example "Example usage:"
        You can fine an example notebook [here](../examples/kandinsky).

        ```python
        import torch
        from diffusers import KandinskyCombinedPipeline

        from wandb_addons.diffusers import KandinskyCallback


        pipe = KandinskyCombinedPipeline.from_pretrained(
            "kandinsky-community/kandinsky-2-1", torch_dtype=torch.float16
        )
        pipe = pipe.to("cuda")

        prompt = [
            "a photograph of an astronaut riding a horse",
            "a photograph of a dragon"
        ]
        negative_prompt = ["ugly, deformed", "ugly, deformed"]
        num_images_per_prompt = 2

        configs = {
            "guidance_scale": 4.0,
            "height": 512,
            "width": 512,
            "prior_guidance_scale": 4.0,
            "prior_num_inference_steps": 25,
        }

        # Create the WandB callback for StableDiffusionPipeline
        callback = KandinskyCallback(
            pipe,
            prompt=prompt,
            negative_prompt=negative_prompt,
            wandb_project="diffusers",
            num_images_per_prompt=num_images_per_prompt,
            configs=configs,
        )

        # Add the callback to the pipeline
        image = pipe(
            prompt,
            negative_prompt=negative_prompt,
            callback=callback,
            num_images_per_prompt=num_images_per_prompt,
            **configs,
        )
        ```

    Arguments:
        pipeline: (Union[DiffusionPipeline, KandinskyCombinedPipeline, KandinskyPipeline])
            The `KandinskyCombinedPipeline` or `KandinskyPipeline` from `diffusers`.
        prompt: (Union[str, List[str]]) The prompt or prompts to guide the image
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
        num_images_per_prompt: (Optional[int]): The number of images to generate per
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
        pipeline: Union[
            DiffusionPipeline, KandinskyCombinedPipeline, KandinskyPipeline
        ],
        prompt: Union[str, List[str]],
        wandb_project: str,
        wandb_entity: Optional[str] = None,
        weave_mode: bool = False,
        num_inference_steps: int = 100,
        num_images_per_prompt: Optional[int] = 1,
        negative_prompt: Optional[Union[str, List[str]]] = None,
        configs: Optional[Dict] = None,
        **kwargs,
    ) -> None:
        super().__init__(
            pipeline,
            prompt,
            wandb_project,
            wandb_entity,
            weave_mode,
            num_inference_steps,
            num_images_per_prompt,
            negative_prompt,
            configs,
            **kwargs,
        )
        self.starting_step = 0
        self.log_step = num_inference_steps - 1

    def generate(self, latents: torch.FloatTensor) -> List:
        images = self.pipeline.movq.decode(latents, force_not_quantize=True)["sample"]
        images = images * 0.5 + 0.5
        images = images.clamp(0, 1)
        images = images.cpu().permute(0, 2, 3, 1).float().numpy()
        images = self.pipeline.numpy_to_pil(images)
        return images
