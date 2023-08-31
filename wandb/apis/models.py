import wandb
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    List,
    NamedTuple,
    Optional,
    Sequence,
    TextIO,
    Tuple,
    Type,
    Union,
)
from wandb.sdk.lib.paths import StrPath
import os


def log_model(
    local_path: StrPath,  # can be path to file or directory - we need to check
    model_name: Optional[str] = None,
    aliases: Optional[List[str]] = None,
) -> None:
    temp_run = False
    if wandb.run is None:
        run = wandb.init(settings=wandb.Settings(silent="true"))
        temp_run = True
    else:
        run = wandb.run
    run.log_artifact(
        artifact_or_path=local_path, name=model_name, type="model", aliases=aliases
    )
    if temp_run:
        run.finish()
    return None


def use_model(model_name: str, aliases: Optional[List[str]] = None) -> StrPath:
    """
    Arguments:
    model_name: (str) A model artifact name.
        May be prefixed with entity/project/. Valid names
        can be in the following forms:
            - name:version
            - name:alias
            - digest
    """
    temp_run = False
    if wandb.run is None:
        run = wandb.init(settings=wandb.Settings(silent="true"))
        temp_run = True
    else:
        run = wandb.run

    artifact = run.use_artifact(artifact_or_name=model_name, aliases=aliases)
    local_path = artifact.download()
    if temp_run:
        run.finish()
    return local_path


def link_model(
    local_path: StrPath,
    linked_model_name: str,
    model_name: Optional[str] = None,
    aliases: Optional[List[str]] = None,
) -> None:
    temp_run = False
    if wandb.run is None:
        run = wandb.init(settings=wandb.Settings(silent="true"))
        temp_run = True
    else:
        run = wandb.run

    name_parts = linked_model_name.split("/")
    assert len(name_parts) == 1
    project = "model-registry"
    target_path = run.entity + "/" + project + "/" + linked_model_name

    artifact = run.log_artifact(
        artifact_or_path=local_path, name=model_name, type="model"
    )
    run.link_artifact(artifact=artifact, target_path=target_path, aliases=aliases)

    if temp_run:
        run.finish()
    return None
