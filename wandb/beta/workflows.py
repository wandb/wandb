from __future__ import annotations

import json
import os
import warnings
from typing import Any

from typing_extensions import deprecated

import wandb
from wandb.data_types import WBValue, _SavedModel
from wandb.proto.wandb_deprecated import Deprecated
from wandb.sdk import wandb_setup
from wandb.sdk.artifacts.artifact import Artifact
from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry
from wandb.sdk.lib.deprecate import deprecate as wandb_deprecate

warnings.warn(
    message=f"The {__name__!r} module is deprecated and will be removed in a future version. Please use the equivalent 'wandb.Run' methods instead.",
    category=DeprecationWarning,
    stacklevel=2,
)


def _add_any(
    artifact: Artifact,
    path_or_obj: str | ArtifactManifestEntry | WBValue,  # todo: add dataframe
    name: str | None,
) -> Any:
    """Add an object to an artifact.

    High-level wrapper to add object(s) to an artifact - calls any of the .add* methods
    under Artifact depending on the type of object that's passed in. This will probably
    be moved to the Artifact class in the future.

    Args:
        artifact: artifact created with `wandb.Artifact(...)`
        path_or_obj: either a str or valid object which indicates what to add
            to an artifact.
        name: the name of the object which is added to an artifact.

    Returns:
        Type[Any] - Union[None, ArtifactManifestEntry, etc]

    """
    if isinstance(path_or_obj, ArtifactManifestEntry):
        return artifact.add_reference(path_or_obj, name)
    elif isinstance(path_or_obj, WBValue):
        return artifact.add(path_or_obj, name)
    elif isinstance(path_or_obj, str):
        if os.path.isdir(path_or_obj):
            return artifact.add_dir(path_or_obj)
        elif os.path.isfile(path_or_obj):
            return artifact.add_file(path_or_obj)
        else:
            with artifact.new_file(name) as f:
                f.write(json.dumps(path_or_obj, sort_keys=True))
    else:
        raise TypeError(
            "Expected `path_or_obj` to be instance of `ArtifactManifestEntry`,"
            f" `WBValue`, or `str, found {type(path_or_obj)}"
        )


def _log_artifact_version(
    name: str,
    type: str,
    entries: dict[str, str | ArtifactManifestEntry | WBValue],
    aliases: str | list[str] | None = None,
    description: str | None = None,
    metadata: dict | None = None,
    project: str | None = None,
    scope_project: bool | None = None,
    job_type: str = "auto",
) -> Artifact:
    """Create an artifact, populate it, and log it with a run.

    If a run is not present, we create one.

    Args:
        name: `str` - name of the artifact. If not scoped to a project, name will be
            suffixed by "-{run_id}".
        type: `str` - type of the artifact, used in the UI to group artifacts of the
            same type.
        entries: `Dict` - dictionary containing the named objects we want added to this
            artifact.
        description: `str` - text description of artifact.
        metadata: `Dict` - users can pass in artifact-specific metadata here, will be
            visible in the UI.
        project: `str` - project under which to place this artifact.
        scope_project: `bool` - if True, we will not suffix `name` with "-{run_id}".
        job_type: `str` - Only applied if run is not present and we create one.
            Used to identify runs of a certain job type, i.e "evaluation".

    Returns:
        Artifact

    """
    run = wandb_setup.singleton().most_recent_active_run
    if not run:
        run = wandb.init(
            project=project,
            job_type=job_type,
            settings=wandb.Settings(silent=True),
        )

    if not scope_project:
        name = f"{name}-{run.id}"

    if metadata is None:
        metadata = {}

    art = wandb.Artifact(name, type, description, metadata, False, None)

    for path in entries:
        _add_any(art, entries[path], path)

    # "latest" should always be present as an alias
    aliases = wandb.util._resolve_aliases(aliases)
    run.log_artifact(art, aliases=aliases)

    return art


_LOG_MODEL_DEPRECATION_MSG = "`log_model` is deprecated and will be removed in a future version. Please use `Run.log_artifact` instead."


@deprecated(_LOG_MODEL_DEPRECATION_MSG)
def log_model(
    model_obj: Any,
    name: str = "model",
    aliases: str | list[str] | None = None,
    description: str | None = None,
    metadata: dict | None = None,
    project: str | None = None,
    scope_project: bool | None = None,
    **kwargs: dict[str, Any],
) -> _SavedModel:
    """Log a model object to enable model-centric workflows in the UI.

    Supported frameworks include PyTorch, Keras, Tensorflow, Scikit-learn, etc. Under
    the hood, we create a model artifact, bind it to the run that produced this model,
    associate it with the latest metrics logged with `run.log(...)` and more.

    Args:
        model_obj: any model object created with the following ML frameworks: PyTorch,
            Keras, Tensorflow, Scikit-learn. name: `str` - name of the model artifact
            that will be created to house this model_obj.
        aliases: `str, List[str]` - optional alias(es) that will be applied on this
            model and allow for unique identification. The alias "latest" will always be
            applied to the latest version of a model.
        description: `str` - text description/notes about the model - will be visible in
            the Model Card UI.
        metadata: `Dict` - model-specific metadata goes here - will be visible the UI.
        project: `str` - project under which to place this artifact.
        scope_project: `bool` - If true, name of this model artifact will not be
            suffixed by `-{run_id}`.

    Returns:
        _SavedModel instance

    Example:
        ```python
        import torch.nn as nn
        import torch.nn.functional as F


        class Net(nn.Module):
            def __init__(self):
                super(Net, self).__init__()
                self.fc1 = nn.Linear(10, 10)

            def forward(self, x):
                x = self.fc1(x)
                x = F.relu(x)
                return x


        model = Net()
        sm = log_model(model, "my-simple-model", aliases=["best"])
        ```

    """
    wandb_deprecate(
        field_name=Deprecated.beta__workflows__log_model,
        warning_message=_LOG_MODEL_DEPRECATION_MSG,
    )

    model = _SavedModel.init(model_obj, **kwargs)
    _ = _log_artifact_version(
        name=name,
        type="model",
        entries={
            "index": model,
        },
        aliases=aliases,
        description=description,
        metadata=metadata,
        project=project,
        scope_project=scope_project,
        job_type="log_model",
    )
    # TODO: handle offline mode appropriately.
    return model


_USE_MODEL_DEPRECATION_MSG = "`use_model` is deprecated and will be removed in a future version. Please update your code to use `Run.use_artifact` instead."


@deprecated(_USE_MODEL_DEPRECATION_MSG)
def use_model(aliased_path: str, unsafe: bool = False) -> _SavedModel:
    """Fetch a saved model from an alias.

    Under the hood, we use the alias to fetch the model artifact containing the
    serialized model files and rebuild the model object from these files. We also
    declare the fetched model artifact as an input to the run (with `run.use_artifact`).

    Args:
        aliased_path: `str` - the following forms are valid: "name:version",
            "name:alias". May be prefixed with "entity/project".
        unsafe: `bool` - must be True to indicate the user understands the risks
            associated with loading external models.

    Returns:
        _SavedModel instance

    Example:
        ```python
        # Assuming the model with the name "my-simple-model" is trusted:
        sm = use_model("my-simple-model:latest", unsafe=True)
        model = sm.model_obj()
        ```
    """
    wandb_deprecate(
        field_name=Deprecated.beta__workflows__use_model,
        warning_message=_USE_MODEL_DEPRECATION_MSG,
    )

    if not unsafe:
        raise ValueError("The 'unsafe' parameter must be set to True to load a model.")

    if ":" not in aliased_path:
        raise ValueError(
            "aliased_path must be of the form 'name:alias' or 'name:version'."
        )

    # Returns a _SavedModel instance
    if run := wandb_setup.singleton().most_recent_active_run:
        artifact = run.use_artifact(aliased_path)
        sm = artifact.get("index")

        if sm is None or not isinstance(sm, _SavedModel):
            raise ValueError(
                "Deserialization into model object failed: _SavedModel instance could not be initialized properly."
            )

        return sm
    else:
        raise ValueError(
            "use_model can only be called inside a run. Please call wandb.init() before use_model(...)"
        )


_LINK_MODEL_DEPRECATION_MSG = "`link_model` is deprecated and will be removed in a future version. Please use `Run.link_artifact` instead."


@deprecated(_LINK_MODEL_DEPRECATION_MSG)
def link_model(
    model: _SavedModel,
    target_path: str,
    aliases: str | list[str] | None = None,
) -> None:
    """Link the given model to a portfolio.

    A portfolio is a promoted collection which contains (in this case) model artifacts.
    Linking to a portfolio allows for useful model-centric workflows in the UI.

    Args:
        model: `_SavedModel` - an instance of _SavedModel, most likely from the output
            of `log_model` or `use_model`.
        target_path: `str` - the target portfolio. The following forms are valid for the
            string: {portfolio}, {project/portfolio},{entity}/{project}/{portfolio}.
        aliases: `str, List[str]` - optional alias(es) that will only be applied on this
            linked model inside the portfolio. The alias "latest" will always be applied
            to the latest version of a model.

    Returns:
        None

    Example:
        sm = use_model("my-simple-model:latest")
        link_model(sm, "my-portfolio")

    """
    wandb_deprecate(
        field_name=Deprecated.beta__workflows__link_model,
        warning_message=_LINK_MODEL_DEPRECATION_MSG,
    )

    aliases = wandb.util._resolve_aliases(aliases)

    if run := wandb_setup.singleton().most_recent_active_run:
        # _artifact_source, if it exists, points to a Public Artifact.
        # Its existence means that _SavedModel was deserialized from a logged artifact, most likely from `use_model`.
        if model._artifact_source:
            artifact = model._artifact_source.artifact
        # If the _SavedModel has been added to a Local Artifact (most likely through `.add(WBValue)`), then
        # model._artifact_target will point to that Local Artifact.
        elif model._artifact_target and model._artifact_target.artifact._final:
            artifact = model._artifact_target.artifact
        else:
            raise ValueError(
                "Linking requires that the given _SavedModel belongs to an artifact"
            )

        run.link_artifact(artifact, target_path, aliases)

    else:
        if model._artifact_source is not None:
            model._artifact_source.artifact.link(target_path, aliases)
        else:
            raise ValueError(
                "Linking requires that the given _SavedModel belongs to a logged artifact."
            )
