import pytest
import wandb
from tensorflow.keras import backend as K
from tensorflow.keras.layers import Dense, Flatten, Reshape
from tensorflow.keras.models import Sequential
from wandb.keras import WandbCallback


@pytest.fixture
def dummy_model(request):
    K.clear_session()
    multi = request.node.get_closest_marker("multiclass")
    image_output = request.node.get_closest_marker("image_output")
    if multi:
        loss = "categorical_crossentropy"
    else:
        loss = "binary_crossentropy"
    nodes = 1 if not multi else 10
    if image_output:
        nodes = 300
    model = Sequential()
    model.add(Flatten(input_shape=(10, 10, 3)))
    model.add(Dense(nodes, activation="sigmoid"))
    if image_output:
        model.add(Dense(nodes, activation="relu"))
        model.add(Reshape((10, 10, 3)))
    model.compile(optimizer="adam", loss=loss, metrics=["accuracy"])
    return model


@pytest.fixture
def dummy_data(request):
    multi = request.node.get_closest_marker("multiclass")
    image_output = request.node.get_closest_marker("image_output")
    cats = 10 if multi else 1
    import numpy as np

    data = np.random.randint(255, size=(100, 10, 10, 3))
    labels = np.random.randint(2, size=(100, cats))
    if image_output:
        labels = data
    return data, labels


def test_keras_resume_best_metric(
    dummy_model, dummy_data, live_mock_server, test_settings
):
    res = live_mock_server.set_ctx({"resume": True})
    print("CTX AFTER UPDATE", res)
    print("GET RIGHT AWAY", live_mock_server.get_ctx())
    wandb.init(reinit=True, resume="allow", settings=test_settings)
    print("Summary", dict(wandb.run.summary))
    print("Config", dict(wandb.run.config))
    assert WandbCallback().best == 0.5
    wandb.finish()
