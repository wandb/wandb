# This file is separated from the main test file in
# order to simulate models defined in external modules.
from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")
tensorflow = pytest.importorskip("tensorflow")
keras = tensorflow.keras
svm = pytest.importorskip("sklearn.svm")
np = pytest.importorskip("numpy")


def sklearn_model():
    return svm.SVC()


def pytorch_model():
    class PytorchModel(torch.nn.Module):
        def __init__(self):
            super().__init__()
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
