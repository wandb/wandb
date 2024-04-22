from enum import Enum
from typing import Any, Callable, List, Optional, Sequence, Union

import wandb
from wandb.sdk.integration_utils.auto_logging import AutologAPI, AutologInitArgs

from .pipeline_resolver import DiffusersPipelineResolver


class DiffusionPipelineOutputType(Enum):
    IMAGE = None
    VIDEO = "video"
    AUDIO = "audio"


class DiffusersAutologAPI(AutologAPI):
    """Autolog API calls to W&B for HuggingFace Diffusers.

    Arguments:
        name: (str) The name of the python module to log. For example, "diffusers".
        symbols: (Sequence[str]) The sequence of functions to log. For example,
            ["StableDiffusionPipeline.__call__"].
        resolver: (DiffusersPipelineResolver) The resolver for the autologger.
        telemetry_feature: (Optional[str]) The telemetry feature to log.
    """

    def __init__(
        self,
        name: str,
        symbols: Sequence[str],
        resolver: DiffusersPipelineResolver,
        telemetry_feature: Optional[str] = None,
    ):
        super().__init__(
            name=name,
            symbols=symbols,
            resolver=resolver,
            telemetry_feature=telemetry_feature,
        )
        self.api_name = self._patch_api.name
        self.symbols = symbols

    def check_pipeline_support(self, pipeline: Union[type, str]) -> bool:
        """Check if the pipeline is supported for logging.

        Arguments:
            pipeline_name: (str) The name of the pipeline.

        Returns:
            True if the pipeline is supported, False otherwise.
        """
        pipeline = pipeline if isinstance(pipeline, str) else pipeline.__qualname__
        return pipeline in self._patch_api.symbols

    def track_pipeline(
        self,
        api_module: Union[Any, str],
        pipeline: Union[type, str],
        kwarg_logging: Optional[List[str]] = None,
        kwarg_actions: Optional[List[Union[Callable, None]]] = None,
        output_type: Optional[
            DiffusionPipelineOutputType
        ] = DiffusionPipelineOutputType.IMAGE,
        table_schema: Optional[List[str]] = None,
    ) -> None:
        """Track the pipeline.

        Arguments:
            api_module: (Union[Any, str]) The module to track.
            pipeline: (Union[type, str]) The pipeline to track.
            kwarg_logging: (Optional[List[str]]) The list of keyword arguments to log.
            kwarg_actions: (Optional[List[Union[Callable, None]]]) The list of keyword actions to log.
            output_type: (Optional[DiffusionPipelineOutputType]) The output type of the pipeline.
            table_schema: (Optional[List[str]]) The schema of the table to log.
        """
        pipeline = pipeline if isinstance(pipeline, str) else pipeline.__qualname__
        self._patch_api.name = str(api_module)
        if pipeline in self._patch_api.symbols:
            wandb.termwarn(f"{pipeline} is already being supported.", repeat=False)
        else:
            kwarg_logging = [] if kwarg_logging is None else kwarg_logging
            kwarg_actions = (
                [None] * len(kwarg_logging) if kwarg_actions is None else kwarg_actions
            )
            assert len(kwarg_logging) == len(
                kwarg_actions
            ), "kwarg_logging and kwarg_actions must have the same length"
            table_schema = kwarg_logging if table_schema is None else table_schema
            table_schema += ["generated_media"]
            kwarg_logging = (
                kwarg_logging[:-1]
                if len(kwarg_logging) == len(table_schema)
                else kwarg_logging
            )
            self.pipeline_registry_config = {
                "table-schema": table_schema,
                "kwarg-logging": kwarg_logging,
                "kwarg-actions": kwarg_actions,
            }
            if output_type not in [None, DiffusionPipelineOutputType.IMAGE]:
                self.pipeline_registry_config["output-type"] = output_type.value
            self._patch_api.resolver.supported_pipelines[pipeline] = (
                self.pipeline_registry_config
            )
            self._patch_api.symbols.append(pipeline + ".__call__")
            self.symbols = self._patch_api.symbols

    def __call__(
        self,
        init: AutologInitArgs = None,
        api_module: Optional[Union[Any, str]] = "diffusers",
        pipeline: Optional[Union[type, str]] = None,
        kwarg_logging: Optional[List[str]] = None,
        kwarg_actions: Optional[List[Union[Callable, None]]] = None,
        output_type: Optional[
            DiffusionPipelineOutputType
        ] = DiffusionPipelineOutputType.IMAGE,
        table_schema: Optional[List[str]] = None,
    ) -> None:
        if pipeline is not None:
            if self.check_pipeline_support(pipeline):
                super().__call__(init)
            if api_module == "diffusers":
                self.track_pipeline(
                    api_module=api_module,
                    pipeline=pipeline,
                    kwarg_logging=kwarg_logging,
                    kwarg_actions=kwarg_actions,
                    output_type=output_type,
                    table_schema=table_schema,
                )
                super().__call__(init)
            else:
                super().__call__(init)
                self.track_pipeline(
                    api_module=api_module,
                    pipeline=pipeline,
                    kwarg_logging=kwarg_logging,
                    kwarg_actions=kwarg_actions,
                    output_type=output_type,
                    table_schema=table_schema,
                )
        else:
            super().__call__(init)
