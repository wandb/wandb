from typing import (
    Any,
    Dict,
    List,
    Optional,
    Union,
)
import os
import wandb.data_types as data_types
from wandb.sdk.interface.artifacts import (
    ArtifactEntry,
    Artifact as ArtifactInterface,
)
import wandb
import pandas as pd


def _add_any(
    artifact: ArtifactInterface,
    path_or_obj: Union[str, ArtifactEntry, data_types.WBValue],  # todo: add dataframe
    name: Optional[str]
    # is_tmp: Optional[bool] = False,
    # checksum: bool = True,
    # max_objects: Optional[int] = None,
):
    if isinstance(path_or_obj, ArtifactEntry):
        return artifact.add_reference(path_or_obj, name)
    elif isinstance(path_or_obj, data_types.WBValue):
        return artifact.add(path_or_obj, name)
    elif isinstance(path_or_obj, str):
        if os.path.isdir(path_or_obj):
            return artifact.add_dir(path_or_obj)
        elif os.path.isfile(path_or_obj):
            return artifact.add_file(path_or_obj)
        else:
            import json

            with artifact.new_file(name) as f:
                f.write(json.dumps(path_or_obj, sort_keys=True))
    else:
        raise ValueError(
            f"Expected `path_or_obj` to be instance of `ArtifactEntry`, `WBValue`, or `str, found {type(path_or_obj)}"
        )


def _log_artifact_version(
    name: str,
    type: str,
    entries: Dict[str, Union[str, ArtifactEntry, data_types.WBValue]],
    aliases: Union[str, List[str]] = [],
    description: Optional[str] = None,
    metadata: dict = {},
    project: Optional[str] = None,
    project_scope: Optional[bool] = None,
    job_type: str = "auto",
) -> ArtifactInterface:
    if wandb.run is None:
        run = wandb.init(
            project=project, job_type=job_type, settings=wandb.Settings(silent="true")
        )
    else:
        run = wandb.run

    if not project_scope:
        name = f"{name}-{run.id}"

    # This is a dirty hack for demo purposes.
    if getattr(run, "history", None):
        metadata.update({"__wb_log_step__": wandb.run.history._step})

    art = wandb.Artifact(name, type, description, metadata, False, None)

    for path in entries:
        _add_any(art, entries[path], path)

    # Double check that "latest" isn't getting killed.
    if isinstance(aliases, str):
        aliases = [aliases]

    if isinstance(aliases, list) and "latest" not in aliases:
        aliases.append("latest")

    run.log_artifact(art, aliases=aliases)

    return art


def log_model(
    model_obj: Any,
    name: str = "model",
    aliases: Optional[Union[str, List[str]]] = None,
    description: Optional[str] = None,
    metadata: dict = {},
    project: Optional[str] = None,
    # evaluation_table:Optional[data_types.Table]=None,
    # serialization_strategy=wandb.serializers.PytorchSerializer,
    # link_to_registry=True
):
    model = data_types.SavedModel(model_obj)
    artifact = _log_artifact_version(
        name=name,
        type="model",
        entries={
            "index": model,
        },
        aliases=aliases,
        description=description,
        metadata=metadata,
        project=project,
        project_scope=False,
        job_type="log_model",
    )

    return model
