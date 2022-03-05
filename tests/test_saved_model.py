import os
import shutil
import platform
import pytest

import wandb
from wandb.sdk.data_types import saved_model as SM
from wandb.apis.public import Artifact
from wandb.apis.public import _DownloadedArtifactEntry
from wandb.sdk.wandb_artifacts import ArtifactEntry


torch = pytest.importorskip("torch")
tensorflow = pytest.importorskip("tensorflow")
keras = tensorflow.keras
svm = pytest.importorskip("sklearn.svm")
np = pytest.importorskip("numpy")


def test_SavedModel_sklearn(runner, mocker):
    savedModel_test(runner, mocker, sklearn_model())


def test_SavedModel_pytorch(runner, mocker):
    savedModel_test(runner, mocker, pytorch_model())


@pytest.mark.skipif(
    platform.system() == "Windows", reason="TODO: Windows is legitimately busted",
)
def test_SavedModel_keras(runner, mocker):
    savedModel_test(runner, mocker, keras_model())


def test_SklearnSavedModel(runner):
    subclass_test(
        runner,
        SM._SklearnSavedModel,
        [sklearn_model()],
        [keras_model(), pytorch_model(),],
    )


def test_PytorchSavedModel(runner):
    subclass_test(
        runner,
        SM._PytorchSavedModel,
        [pytorch_model()],
        [keras_model(), sklearn_model(),],
    )


@pytest.mark.skipif(
    platform.system() == "Windows", reason="TODO: Windows is legitimately busted",
)
def test_TensorflowKerasSavedModel(runner):
    subclass_test(
        runner,
        SM._TensorflowKerasSavedModel,
        [keras_model()],
        [sklearn_model(), pytorch_model()],
    )


def sklearn_model():
    return svm.SVC()


def pytorch_model():
    class PytorchModel(torch.nn.Module):
        def __init__(self):
            super(PytorchModel, self).__init__()
            self.hidden_layer = torch.nn.Linear(1, 1)
            self.hidden_layer.weight = torch.nn.Parameter(torch.tensor([[1.58]]))
            self.hidden_layer.bias = torch.nn.Parameter(torch.tensor([-0.14]))

            self.output_layer = torch.nn.Linear(1, 1)
            self.output_layer.weight = torch.nn.Parameter(torch.tensor([[2.45]]))
            self.output_layer.bias = torch.nn.Parameter(torch.tensor([-0.11]))

        def forward(self, x):
            x = torch.sigmoid(self.hidden_layer(x))
            x = torch.sigmoid(self.output_layer(x))
            return x

    return PytorchModel()


def keras_model():
    def get_model():
        # Create a simple model.
        inputs = keras.Input(shape=(32,))
        outputs = keras.layers.Dense(1)(inputs)
        model = keras.Model(inputs, outputs)
        model.compile(optimizer="adam", loss="mean_squared_error")
        return model

    model = get_model()

    # Train the model.
    test_input = np.random.random((128, 32))
    test_target = np.random.random((128, 1))
    model.fit(test_input, test_target)

    return model


# These classes are used to patch the API
# so we can simulate downloading an artifact without
# actually making a network round trip (using the local filesystem)
class DownloadedArtifactEntryPatch(_DownloadedArtifactEntry):
    def download(self, root=None):
        root = root or self._parent_artifact._default_root()
        return self.copy(self.local_path, os.path.join(root, self.name))


class ArtifactEntryPatch(ArtifactEntry):
    def download(self, root=None):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        shutil.copyfile(self.local_path, self.path)
        return self.path


def make_local_artifact_public(art, mocker):
    mocker.patch(
        "wandb.apis.public._DownloadedArtifactEntry", DownloadedArtifactEntryPatch
    )
    mocker.patch("wandb.sdk.wandb_artifacts.ArtifactEntry", ArtifactEntryPatch)

    pub = Artifact(
        None,
        "FAKE_ENTITY",
        "FAKE_PROJECT",
        "FAKE_NAME",
        {
            "artifactSequence": {"name": "FAKE_SEQUENCE_NAME",},
            "aliases": [],
            "id": "FAKE_ID",
            "digest": "FAKE_DIGEST",
            "state": None,
            "size": None,
            "createdAt": None,
            "updatedAt": None,
            "artifactType": {"name": "FAKE_TYPE_NAME",},
        },
    )
    pub._manifest = art._manifest
    for val in pub._manifest.entries.values():
        val.__class__ = ArtifactEntryPatch
    return pub


# External SavedModel tests (user facing)
def savedModel_test(runner, mocker, model):
    with pytest.raises(TypeError):
        _ = SM.SavedModel(model)
    sm = SM.SavedModel.init(model)
    with runner.isolated_filesystem():
        art = wandb.Artifact("name", "type")
        art.add(sm, "model")
        assert art.manifest.entries[f"model.{sm._log_type}.json"] is not None
        pub_art = make_local_artifact_public(art, mocker)
        sm2 = pub_art.get("model")
        assert sm2 is not None


# # Internal adapter tests (non user facing)
def subclass_test(
    runner, adapter_cls, valid_models, invalid_models,
):
    # Verify valid models can be adapted
    for model in valid_models:
        assert adapter_cls._validate_obj(model)

    # Verify invalid models are denied
    for model in invalid_models:
        assert not adapter_cls._validate_obj(model)

    # Verify file-level serialization and deserialization
    with runner.isolated_filesystem():
        i = 0
        for model in valid_models:
            path = adapter_cls._tmp_path()
            adapter_cls._serialize(model, path)
            model2 = adapter_cls._deserialize(path)
            assert model2 is not None
