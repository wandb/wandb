from typing import (
    Any,
    Dict,
    List,
    Optional,
    Union,
)
import os
import wandb.data_types as data_types
from wandb.data_types import SavedModel
from wandb.sdk.interface.artifacts import (
    ArtifactEntry,
    Artifact as ArtifactInterface,
)

from collections import defaultdict
from wandb.sdk.wandb_artifacts import Artifact as LocalArtifact
from wandb.apis.public import Artifact as PublicArtifact
from wandb.apis import InternalApi, PublicApi
from wandb.apis import internal, public
from wandb.data_types import SavedModel
import wandb


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
) -> "SavedModel":
    model = data_types.SavedModel(model_obj)
    artifact = _log_artifact_version(
        name=name,
        type="model",
        entries={"index": model,},
        aliases=aliases,
        description=description,
        metadata=metadata,
        project=project,
        project_scope=False,
        job_type="log_model",
    )

    # TODO: handle offline mode appropriately.
    # Do not do .wait() --> it's blocking and synchronous.
    # We want this done asynchronously.
    # Do client id and server id mapping on backend for linkartifact.
    # artifactsaver, createArtifact mutation.
    # many to one relationship from sequence_client_id to relevant server id.
    # artifact.wait()

    # Once this completes, we will have uploaded the artifact.
    # `artifact._logged_artifact._instance` points to the Public Artifact.
    # Property access on `artifact` will be routed to this Public Artifact.
    # model._set_artifact_source(artifact._logged_artifact._instance)

    # Now the SavedModel() instance has the Public Artifact bound to it.
    # In `link_model`, we can now call properties on this Public Artifact.
    # including id, which will be used in the gql request.
    return model


def use_model(model_alias: str):
    # Returns a SavedModel instance
    pass


def link_model(
    model: "SavedModel",
    registry_path: str,
    aliases: Optional[Union[str, List[str]]] = None,
):
    """
    `registry_name`: str that can take the following form:
        "{portfolio}"
        "{entity}/{project}/{portfolio}"
        "{project}/{portfolio}
    """

    if aliases is None:
        aliases = ["latest"]

    if wandb.run:
        run = wandb.run
        # _artifact_target is a Local Artifact
        # In this case, the given SavedModel was added to a LocalArtifact, most likely through `.add(WBValue)`

        if model._artifact_target is not None:
            artifact = model._artifact_target.artifact
        # _artifact_source is a Public Artifact here.
        # Its existence means that SavedModel was deserialized from an artifact, most likely from `use_model`.
        elif model._artifact_source is not None:
            artifact = model._artifact_source.artifact
        else:
            raise ValueError(
                "Linking requires that the given SavedModel belongs to an artifact"
            )

        run.link_artifact(artifact, registry_path, aliases)

    else:
        if model._artifact_source is not None:
            model._artifact_source.artifact.link(registry_path, aliases)
        else:
            raise ValueError(
                "Linking requires that the given SavedModel belongs to an artifact"
            )

    # TODO: Will delete the below code/comments.

    # # SavedModel instance contains a reference to its underlying artifact.
    # # If it's a Public Artifact, i.e it's been logged to the backend already,
    # # we can simply use its link method.
    # if model._artifact_target is not None:
    #     public_artifact = model._artifact_target.artifact._logged_artifact
    #     # TODO: we should have a constraint that all linked artifacts in a portfolio
    #     # have the same artifact type: i.e all "model" or "dataset".
    #     # TODO: This is synchronous

    #     return public_artifact.link(registry_path, aliases)

    # if wandb.run:
    #     # TODO: This is async
    #     artifact = model._artifact_source.artifact
    #     wandb.run.link_artifact(artifact, registry_path, aliases)

    # artifact here is a LocalArtifact.
    # We make the assumption here that if someone calls log_model 5 times
    # (which logs an artifact 5 times) & then calls link_model...
    # There's no guarantee that the artifact actually exists on the backend.
    # So instead in the linkArtifact gql request, we have to send the client_id
    # of the LocalArtifact. And in the resolver, we check to see if we have a
    # server_id mapped. If yes, we use that and continue link logic.
    # If not, we error out and rely on the client retrying requests.
    # TODO: How does the client retry request work?

    # Use Case: a user wants to evaluate a batch of models and
    # link the best one into a portfolio.

    # Use Case: a user wants to evaluate all the models in a portfolio
    # and choose the best one to link into the next stage (next portfolio).

    # Use Case: a user wants to evaluate the latest models in a portfolio
    # and choose the best one to link into the next stage (next portfolio).

    # Automated retraining: a user wants to fire off a training run on new data
    # with the same model architecture. They then want to link this model
    # into one portfolio to compare against the production model.

    # If we're not in a run context OR SavedModels' underlying artifact
    # is a Public Artifact, use the public API's link_artifact.
    # this straight away fires up a linkArtifact gql request.

    # Use Case: a user trains a model, calling log_model several times
    # in a row and saves a reference to the best model every time.
    # At the end, they want to link this model into a portfolio.

    # --> this is going to be in a run context.
    # --> link_model(best_model, "mnist_1")
    # --> best_model's underlying artifact may not be logged yet.
    # --> run.link_artifact("Union[LocalArtifact, PublicArtifact]")

    # The below case is going to be more common.
    # I can imagine that a user calls log_model several times in a row
    # or evaluates a batch of models and wants to link the best one.
    # In that case, we would use_model, get the SavedModel instance,
    # and
    # If we are in a run context, use run.link_artifact
    # In this case, if SavedModel's artifact hasn't been logged yet,
    # this accepts a Union[LocalArtifact, PublicArtifact].

    # if we're not in the context of a run,
    pass


def link_artifact(
    artifact: "PublicArtifact",
    registry_name: str,
    aliases: Union[str, List[str]] = None,
) -> None:

    if wandb.run is None:
        raise ValueError("wandb.init() must be called before artifact can be linked")

    run = wandb.run
    # TODO: handle offline mode appropriately
    if run.settings._offline:
        raise TypeError("Cannot link artifact when in offline mode.")

    api = internal.Api(default_settings={"entity": run.entity, "project": run.project})
    api.set_current_run_id(run.id)

    api.link_artifact(artifact.id, registry_name, aliases)

    if model_artifact.id is None:
        # TODO: change error message
        raise ValueError("model_artifact has not been logged")

    pfolio_id = get_portfolio(portfolio_name)
    # pfolio = api.artifact_collection(portfolio_name, "model")

    mutation = gql(
        """
        mutation linkArtifact($artifactID: ID!, $artifactPortfolioID: ID!, $aliases: [ArtifactAliasInput!]) {
            linkArtifact(input: {
                artifactID: $artifactID,
                artifactPortfolioID: $artifactPortfolioID,
                aliases: $aliases
            }) {
                artifactMembership {
                    versionIndex
                }
            }
        }
        """
    )
    aliases = [
        {"artifactCollectionName": portfolio_name, "alias": alias} for alias in aliases
    ]

    response = api.client.execute(
        mutation,
        variable_values={
            "artifactID": model_artifact.id,
            "artifactPortfolioID": pfolio_id,
            "aliases": aliases,
        },
    )

    if (
        response is None
        or response.get("linkArtifact") is None
        or response["linkArtifact"].get("artifactMembership") is None
        or response["linkArtifact"].get("artifactMembership").get("versionIndex")
        is None
    ):
        raise ValueError("Error in GraphQL response")

    version_index = response["linkArtifact"]["artifactMembership"]["versionIndex"]
    print(f"Version index (0-based): {version_index}")
    return model_artifact
