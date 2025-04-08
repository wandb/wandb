import os
import pathlib
import tempfile

import cloudpickle
import pytest
import torch
import wandb
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


# TODO: uncomment this once the test is fixed
# @pytest.mark.skipif(
#     platform.system() == "Windows",
#     reason="TODO: Windows is legitimately busted",
# )
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


# TODO: uncomment this once the test is fixed
# @pytest.mark.skipif(
#     platform.system() == "Windows",
#     reason="TODO: Windows is legitimately busted",
# )
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
        # TODO: Uncomment once _TensorflowKerasSavedModel._serialize is fixed.
        # (
        #     keras_model,
        #     saved_model._TensorflowKerasSavedModel,
        #     "keras",
        #     lambda model, path: model.save(path),
        # ),
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
def test_saved_model_path(model_fn, model_cls, file_ext, save_fn):
    temp_dir = tempfile.mkdtemp()
    model_path = pathlib.Path(temp_dir) / f"my_model.{file_ext}"

    model = model_fn()
    save_fn(model, model_path)

    model_cls(model_path)


# These classes are used to patch the API
# so we can simulate downloading an artifact without
# actually making a network round trip (using the local filesystem)
class ArtifactManifestEntryPatch(ArtifactManifestEntry):
    def download(self, root=None):
        root = root or self._parent_artifact._default_root()
        dest = os.path.join(root, self.path)
        return copy_or_overwrite_changed(self.local_path, dest)

    def _referenced_artifact_id(self):
        return None


class ArtifactPatch(Artifact):
    def _load_manifest(self, url: str) -> None:
        assert url == "FAKE_URL"


def make_local_artifact_public(art):
    pub = ArtifactPatch._from_attrs(
        "FAKE_ENTITY",
        "FAKE_PROJECT",
        "FAKE_NAME",
        {
            "id": "FAKE_ID",
            "artifactType": {
                "name": "FAKE_TYPE_NAME",
            },
            "aliases": [
                {
                    "artifactCollection": {
                        "project": {
                            "entityName": "FAKE_ENTITY",
                            "name": "FAKE_PROJECT",
                        },
                        "name": "FAKE_NAME",
                    },
                    "alias": "v0",
                }
            ],
            "artifactSequence": {
                "name": "FAKE_SEQUENCE_NAME",
                "project": {
                    "entityName": "FAKE_ENTITY",
                    "name": "FAKE_PROJECT",
                },
            },
            "versionIndex": 0,
            "description": None,
            "metadata": None,
            "state": "COMMITTED",
            "currentManifest": {
                "file": {
                    "directUrl": "FAKE_URL",
                }
            },
            "commitHash": "FAKE_HASH",
            "fileCount": 0,
            "createdAt": None,
            "updatedAt": None,
        },
        None,
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

    mocker.patch(
        "wandb.sdk.artifacts.artifact.ArtifactManifestEntry",
        ArtifactManifestEntryPatch,
    )
    art = wandb.Artifact("name", "type")
    art.add(sm, "model")
    assert art.manifest.entries[f"model.{sm._log_type}.json"] is not None
    pub_art = make_local_artifact_public(art)
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
