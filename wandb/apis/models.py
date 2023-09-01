from typing import List, Optional

import wandb
from wandb.sdk.lib.paths import StrPath


def log_model(
    local_path: StrPath,
    model_name: Optional[str] = None,
    aliases: Optional[List[str]] = None,
) -> None:
    """Declare a model artifact as an output of a run.

    Arguments:
        local_path: (str) A path to the contents of this model,
            can be in the following forms:
                - `/local/directory`
                - `/local/directory/file.txt`
                - `s3://bucket/path`
        model_name: (str, optional) An artifact name. May be prefixed with entity/project.
            Valid names can be in the following forms:
                - name:version
                - name:alias
                - digest.
            This will default to the basename of the path prepended with the current
            run id  if not specified.
        aliases: (list, optional) Aliases to apply to this artifact,
                defaults to `["latest"]`

    Returns:
        None
    """
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


def use_model(model_name: str) -> StrPath:
    """Download a logged model artifact.

    Arguments:
        model_name: (str) A model artifact name.
            May be prefixed with entity/project/. Valid names
            can be in the following forms:
                - name:version
                - name:alias
                - digest.
    """
    temp_run = False
    if wandb.run is None:
        run = wandb.init(settings=wandb.Settings(silent="true"))
        temp_run = True
    else:
        run = wandb.run

    artifact = run.use_artifact(artifact_or_name=model_name)
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
    """Link a model version to a model portfolio (a promoted collection of model artifacts).

    The linked model will be visible in the UI for the specified portfolio.

    Arguments:
        local_path: (str) A path to the contents of this model,
            can be in the following forms:
                - `/local/directory`
                - `/local/directory/file.txt`
                - `s3://bucket/path`
        link_model_name: (str) - the name of the portfolio that the model is to be linked to. The entity will be derived from the run
        aliases: (List[str], optional) - alias(es) that will only be applied on this linked artifact
            inside the portfolio.
            The alias "latest" will always be applied to the latest version of an artifact that is linked.

    Returns:
        None
    """
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
