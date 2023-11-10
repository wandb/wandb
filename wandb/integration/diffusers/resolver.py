import logging
import inspect
from typing import Any, Dict, Sequence

import wandb
from wandb.sdk.integration_utils.auto_logging import Response
from .utils import chunkify


logger = logging.getLogger(__name__)


SUPPORTED_PIPELINES = {
    "StableDiffusionPipeline": {
        "table-schema": ["Prompt", "Negative-Prompt", "Generated-Image"],
        "kwarg-logging": ["prompt", "negative_prompt"],
    },
}


class DiffusersTextToImagePipelineResolver:
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
            logger.warning(e)
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
        if "generator" in kwargs:
            generator = kwargs.pop("generator", None)
            kwargs["seed"] = (
                generator.get_state().to("cpu").tolist()[0]
                if generator is not None
                else None
            )
        return kwargs

    def prepare_table(self, pipeline_configs: Dict[str, Any]) -> wandb.Table:
        columns = []
        pipeline_name = pipeline_configs["pipeline-name"]
        if pipeline_name in SUPPORTED_PIPELINES:
            columns += SUPPORTED_PIPELINES[pipeline_name]["table-schema"]
        return wandb.Table(columns=columns)

    def prepare_loggable_dict(
        self,
        pipeline_configs: Dict[str, Any],
        response: Response,
        kwargs: Dict[str, Any],
    ) -> Dict[str, Any]:
        table = self.prepare_table(pipeline_configs)
        images = response.images
        loggable_kwarg_ids = SUPPORTED_PIPELINES[pipeline_configs["pipeline-name"]][
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
                table.add_data(*table_row)
        return {"text-to-image": table}
