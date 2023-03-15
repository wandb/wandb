import os
import logging
from typing import Any, List, Union, Optional

import wandb
import tensorflow as tf


logger = logging.getLogger(__name__)

OPTIONAL_ARGS_TYPE = Optional[Union[Union[Any, None], List[Union[Any, None]]]]
MODEL_TYPE = Union[tf.keras.Model, List[tf.keras.Model]]


def load_model_from_artifact(
    artifact_address: str,
    artifact_type: str = "model",
    track_lineage: bool = True,
    verbose: bool = True,
    model_filepaths: Optional[List[str]] = None,
    custom_objects: OPTIONAL_ARGS_TYPE = None,
    compile: Union[bool, List[bool]] = True,
    options: OPTIONAL_ARGS_TYPE = None,
) -> MODEL_TYPE:
    if wandb.run is not None:
        model_artifact_dir = (
            wandb.Api().artifact(artifact_address, type=artifact_type).download()
        )
    else:
        if track_lineage:
            model_artifact_dir = wandb.use_artifact(
                artifact_address, type=artifact_type
            ).download()
        else:
            model_artifact_dir = (
                wandb.Api().artifact(artifact_address, type=artifact_type).download()
            )

    if model_filepaths is None:
        return tf.keras.models.load_model(
            model_artifact_dir,
            custom_objects=custom_objects,
            compile=compile,
            options=options,
        )
    else:
        models = []
        for idx, filepath in enumerate(model_filepaths):
            if verbose:
                wandb.termlog(f"loading model {idx + 1}/{len(model_filepaths)}")
                logger.info(f"loading model {idx + 1}/{len(model_filepaths)}")

            filepath = os.path.join(model_artifact_dir, filepath)

            current_model_custom_objects = (
                custom_objects
                if not isinstance(custom_objects, list)
                else custom_objects[idx]
            )
            current_model_compile = (
                compile if not isinstance(compile, list) else compile[idx]
            )
            current_model_options = (
                options if not isinstance(options, list) else options[idx]
            )

            model = tf.keras.models.load_model(
                model_artifact_dir,
                custom_objects=current_model_custom_objects,
                compile=current_model_compile,
                options=current_model_options,
            )
            models.append(model)

        return models
