from __future__ import annotations

import os

import cloudpickle
import pytest
import torch
import wandb
from pytest_mock import MockerFixture
from wandb.apis.public.api import RetryingClient
from wandb.sdk.artifacts._generated import ArtifactFragment
from wandb.sdk.artifacts.artifact import Artifact
from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry
from wandb.sdk.data_types import saved_model
from wandb.sdk.lib.filesystem import copy_or_overwrite_changed

from . import saved_model_constructors

sklearn_model = saved_model_constructors.sklearn_model
pytorch_model = saved_model_constructors.pytorch_model
keras_model = saved_model_constructors.keras_model


def test_saved_model_sklearn(mocker):
    saved_model_test(mocker, sklearn_model())


def test_saved_model_pytorch(mocker):
    saved_model_test(
        mocker,
        pytorch_model(),
        [os.path.abspath(saved_model_constructors.__file__)],
    )


@pytest.mark.skip(reason="New keras release broke this test")
def test_saved_model_keras(mocker):
    saved_model_test(mocker, keras_model())


def test_sklearn_saved_model():
    subclass_test(
        saved_model._SklearnSavedModel,
        [sklearn_model()],
        [
            keras_model(),
            pytorch_model(),
        ],
    )


def test_pytorch_saved_model():
    subclass_test(
        saved_model._PytorchSavedModel,
        [pytorch_model()],
        [
            keras_model(),
            sklearn_model(),
        ],
    )


@pytest.mark.skip(reason="New keras release broke this test")
def test_tensorflow_keras_saved_model():
    subclass_test(
        saved_model._TensorflowKerasSavedModel,
        [keras_model()],
        [sklearn_model(), pytorch_model()],
    )


@pytest.mark.parametrize(
    (
        "model_fn",
        "model_cls",
        "file_ext",
        "save_fn",
    ),
    [
        (
            sklearn_model,
            saved_model._SklearnSavedModel,
            "pkl",
            lambda model, path: cloudpickle.dump(model, open(path, "wb")),
        ),
        (
            pytorch_model,
            saved_model._PytorchSavedModel,
            "pt",
            lambda model, path: torch.save(
                model,
                path,
                pickle_module=cloudpickle,
            ),
        ),
    ],
)
def test_saved_model_path(
    model_fn,
    model_cls,
    file_ext,
    save_fn,
    tmp_path,
):
    model_path = tmp_path / f"my_model.{file_ext}"

    model = model_fn()
    save_fn(model, model_path)

    model_cls(model_path)


class ArtifactPatch(Artifact):
    def _fetch_manifest(self) -> None:  # type: ignore
        return None


def make_local_artifact_public(art: Artifact, mocker: MockerFixture):
    from wandb.sdk.artifacts._validators import FullArtifactPath

    path = FullArtifactPath(
        prefix="FAKE_ENTITY",
        project="FAKE_PROJECT",
        name="FAKE_NAME",
    )
    fragment = ArtifactFragment(
        id="FAKE_ID",
        artifactType={"name": "FAKE_TYPE_NAME"},
        aliases=[
            {
                "id": "FAKE_ALIAS_ID",
                "alias": "v0",
                "artifactCollection": {
                    "__typename": "ArtifactSequence",
                    "name": path.name,
                    "project": {
                        "name": path.project,
                        "entity": {"name": path.prefix},
                    },
                },
            }
        ],
        artifactSequence={
            "name": "FAKE_SEQUENCE_NAME",
            "project": {
                "name": path.project,
                "entity": {"name": path.prefix},
            },
        },
        versionIndex=0,
        description=None,
        tags=[],
        ttlDurationSeconds=-2,
        ttlIsInherited=False,
        metadata=None,
        state="COMMITTED",
        size=0,
        digest="FAKE_DIGEST",
        commitHash="FAKE_HASH",
        fileCount=0,
        createdAt="FAKE_CREATED_AT",
        updatedAt=None,
        historyStep=None,
    )
    pub = ArtifactPatch._from_attrs(
        path,
        fragment,
        client=mocker.Mock(spec=RetryingClient),
    )
    pub._manifest = art._manifest
    return pub


# External SavedModel tests (user facing)
def saved_model_test(mocker, model, py_deps=None):
    with pytest.raises(TypeError):
        _ = saved_model._SavedModel(model)
    kwargs = {}
    if py_deps:
        kwargs["dep_py_files"] = py_deps
    sm = saved_model._SavedModel.init(model, **kwargs)

    # Patch the download method of the ArtifactManifestEntry
    # so we can simulate downloading an artifact without
    # actually making a network round trip (using the local filesystem)
    def _mock_download(self, root=None, skip_cache=None, executor=None):
        root = root or self._parent_artifact._default_root()
        dest = os.path.join(root, self.path)
        return copy_or_overwrite_changed(self.local_path, dest)

    mocker.patch.object(
        ArtifactManifestEntry,
        "download",
        autospec=True,
        side_effect=_mock_download,
    )
    mocker.patch.object(
        ArtifactManifestEntry,
        "_referenced_artifact_id",
        autospec=True,
        return_value=None,
    )

    art = wandb.Artifact("name", "type")
    art.add(sm, "model")
    assert art.manifest.entries[f"model.{sm._log_type}.json"] is not None
    pub_art = make_local_artifact_public(art, mocker)
    sm2 = pub_art.get("model")
    assert sm2 is not None


# # Internal adapter tests (non user facing)
def subclass_test(
    adapter_cls,
    valid_models,
    invalid_models,
):
    # Verify valid models can be adapted
    for model in valid_models:
        assert adapter_cls._validate_obj(model)

    # Verify invalid models are denied
    for model in invalid_models:
        assert not adapter_cls._validate_obj(model)

    # Verify file-level serialization and deserialization
    for model in valid_models:
        path = adapter_cls._tmp_path()
        adapter_cls._serialize(model, path)
        model2 = adapter_cls._deserialize(path)
        assert model2 is not None
