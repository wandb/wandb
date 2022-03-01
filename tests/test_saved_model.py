from wandb.sdk.data_types import SavedModel as SM
from sklearn import svm
import torch
from tensorflow import keras
import numpy as np


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


def test_SklearnModelAdapter_can_adapt_model():
    assert SM._SklearnModelAdapter.can_adapt_model(
        sklearn_model()
    ), "Expect _SklearnModelAdapter to be able to adapt sklearn model"
    assert not SM._SklearnModelAdapter.can_adapt_model(
        pytorch_model()
    ), "Expect _SklearnModelAdapter NOT to be able to adapt sklearn model"
    assert not SM._SklearnModelAdapter.can_adapt_model(
        keras_model()
    ), "Expect _SklearnModelAdapter NOT to be able to adapt sklearn model"


# TODO: Code:
# Get the directory stuff working for artifacts and media types
# TODO: Tests
# Each adapter type:
#   - can adapt
#   - init from path
#   - Save model
#  Saved Model
#  - Init From each type
#  - Init from unsupported type
#  - Add to artifact (and load from artifact - may require new test harness)
