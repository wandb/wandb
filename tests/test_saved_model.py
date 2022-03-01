import wandb
from wandb.sdk.data_types import SavedModel as SM
from sklearn import svm
import torch
from tensorflow import keras
import numpy as np
import os


def test_SavedModel_sklearn(runner):
    savedModel_test(runner, sklearn_model())


def test_SavedModel_pytorch(runner):
    savedModel_test(runner, pytorch_model())


def test_SavedModel_keras(runner):
    savedModel_test(runner, keras_model())


def test_SklearnModelAdapter(runner):
    adapter_test(
        runner,
        SM._SklearnModelAdapter,
        [sklearn_model()],
        [keras_model(), pytorch_model(),],
    )


def test_PytorchModelAdapter(runner):
    adapter_test(
        runner,
        SM._PytorchModelAdapter,
        [pytorch_model()],
        [keras_model(), sklearn_model(),],
    )


def test_TensorflowKerasSavedModelAdapter(runner):
    adapter_test(
        runner,
        SM._TensorflowKerasSavedModelAdapter,
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


# External SavedModel tests (user facing)
def savedModel_test(runner, model):
    sm = SM.SavedModel(model)
    with runner.isolated_filesystem():
        art = wandb.Artifact("name", "type")
        art.add(sm, "model")
        assert art.manifest.entries["model.saved-model.json"] is not None
        # This is almost certainly going to fail without a special harness
        sm2 = art.get("model")


# Internal adapter tests (non user facing)
def adapter_test(
    runner, adapter_cls, valid_models, invalid_models,
):
    # Verify valid models can be adapted
    for model in valid_models:
        assert adapter_cls.can_adapt_model(model)

    # Verify invalid models are denied
    for model in invalid_models:
        assert not adapter_cls.can_adapt_model(model)

    # Verify file-level serialization and deserialization
    with runner.isolated_filesystem():
        i = 0
        for model in valid_models:
            adapter = adapter_cls(model)
            dirpath = os.path.join(".", f"adapter_dir_{i}")
            os.makedirs(dirpath)
            adapter.save_model(dirpath)
            adapter2 = adapter_cls.maybe_init_from_path(dirpath)
            assert adapter2 is not None
