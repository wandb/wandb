import logging
import inspect
from typing import Any, Dict, Sequence

import wandb
from wandb.sdk.integration_utils.auto_logging import Response
from wandb.sdk.lib.runid import generate_id


logger = logging.getLogger(__name__)


TEXT_TO_IMAGE_PIPELINES = [
    "StableDiffusionPipeline",
]


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

            # Prepare the wandb.Table
            table = self.prepare_table(pipeline_configs, kwargs)
            return {"text-to-image": table, **kwargs}
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
        return kwargs

    def prepare_table(
        self, pipeline_configs: Dict[str, Any], kwargs: Dict[str, Any]
    ) -> wandb.Table:
        columns = []
        if pipeline_configs["pipeline-name"] in TEXT_TO_IMAGE_PIPELINES:
            columns += ["Prompt", "Negative-Prompt", "Generated-Image"]
        return wandb.Table(columns=columns)

    def get_latest_id(self):
        return self.autolog_id