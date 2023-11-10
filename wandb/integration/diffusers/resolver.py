import logging
import inspect
from typing import Any, Dict, Sequence

import wandb
from wandb.sdk.integration_utils.auto_logging import Response
from wandb.sdk.lib.runid import generate_id
from .utils import chunkify


logger = logging.getLogger(__name__)


TEXT_TO_IMAGE_PIPELINES = {
    "StableDiffusionPipeline": {
        "table-schema": ["Prompt", "Negative-Prompt", "Generated-Image"],
        "kwarg-logging": ["prompt", "negative_prompt"],
    }
}


class DiffusersPipelineResolver:
    autolog_id = None

    def __call__(
        self,
        args: Sequence[Any],
        kwargs: Dict[str, Any],
        response: Response,
        start_time: float,
        time_elapsed: float,
    ) -> Any:
        pass

        try:
            self.autolog_id = generate_id(length=16)

            # Get the pipeline and the args
            pipeline, args = args[0], args[1:]

            # Update the Kwargs so that they can be logged easily
            kwargs = self.get_updated_kwargs(pipeline, args, kwargs)

            # Get the pipeline configs
            pipeline_configs = dict(pipeline.config)
            pipeline_configs["pipeline-name"] = pipeline.__class__.__name__

            wandb.config.update({"pipeline": pipeline_configs, "params": kwargs})

            # Return the WandB loggable dict
            loggable_dict = self.prepare_loggable_dict(
                pipeline_configs, response, kwargs
            )
            return loggable_dict
        except Exception as e:
            print(e)
        return None

    def get_updated_kwargs(
        self, pipeline: Any, args: Sequence[Any], kwargs: Dict[str, Any]
    ) -> Dict[str, Any]:
        pipeline_call_parameters = list(
            inspect.signature(pipeline.__call__).parameters.items()
        )
        for idx, arg in enumerate(args):
            kwargs[pipeline_call_parameters[idx][0]] = arg
        for pipeline_parameter in pipeline_call_parameters:
            if pipeline_parameter[0] not in kwargs:
                kwargs[pipeline_parameter[0]] = pipeline_parameter[1].default
        return kwargs

    def prepare_table(
        self, pipeline_configs: Dict[str, Any], kwargs: Dict[str, Any]
    ) -> wandb.Table:
        columns = []
        if pipeline_configs["pipeline-name"] in TEXT_TO_IMAGE_PIPELINES:
            columns += TEXT_TO_IMAGE_PIPELINES[pipeline_configs["pipeline-name"]][
                "table-schema"
            ]
        return wandb.Table(columns=columns)

    def prepare_loggable_dict(
        self,
        pipeline_configs: Dict[str, Any],
        response: Response,
        kwargs: Dict[str, Any],
    ) -> Dict[str, Any]:
        table = self.prepare_table(pipeline_configs, kwargs)
        images = response.images
        prompt_logging = (
            kwargs["prompt"]
            if isinstance(kwargs["prompt"], list)
            else [kwargs["prompt"]]
        )
        negative_prompt_logging = (
            kwargs["negative_prompt"]
            if isinstance(kwargs["negative_prompt"], list)
            else [kwargs["negative_prompt"]]
        )
        images = chunkify(images, len(prompt_logging))
        for idx in range(len(prompt_logging)):
            for image in images[idx]:
                wandb.log(
                    {"Generated-Image": wandb.Image(image, caption=prompt_logging[idx])}
                )
                table.add_data(
                    prompt_logging[idx],
                    negative_prompt_logging[idx],
                    wandb.Image(image),
                )
        return {"text-to-image": table}

    def get_latest_id(self):
        return self.autolog_id
