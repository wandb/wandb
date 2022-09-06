import sys

import pytest
import wandb
from tensorflow.keras import backend as K  # noqa: N812
from tensorflow.keras.layers import LSTM, Concatenate, Dense, Embedding, Flatten, Input
from tensorflow.keras.models import Model, Sequential
from wandb.keras import WandbCallback


def test_no_init():
    with pytest.raises(wandb.errors.Error):
        WandbCallback()


def test_keras_image_bad_data():
    import numpy as np

    K.clear_session()
    model = Sequential()
    model.add(Flatten(input_shape=(10, 10, 3)))
    model.add(Dense(1, activation="sigmoid"))
    model.compile(optimizer="adam", loss="binary_crossentropy", metrics=["accuracy"])

    data = np.random.randint(255, size=(100, 10, 10, 3))
    labels = np.random.randint(2, size=(100, 1))

    with pytest.raises(ValueError):
        model.fit(
            data,
            labels,
            epochs=2,
            batch_size=36,
            validation_data=(data.reshape(10), labels),
            callbacks=[
                WandbCallback(data_type="image"),
            ],
        )


def test_keras_convert_sequential():
    # necessary to keep the names of the layers consistent
    K.clear_session()

    model = Sequential()
    model.add(Dense(4, input_shape=(3,)))
    model.add(Dense(5))
    model.add(Dense(6))
    wandb_model = wandb.data_types.Graph.from_keras(model)
    wandb_model_out = wandb.Graph._to_graph_json(wandb_model)
    print(wandb_model_out)
    assert wandb_model_out == {
        "format": "keras",
        "nodes": [
            {
                "name": "dense_input",
                "id": "dense_input",
                "class_name": "InputLayer",
                "output_shape": [(None, 3)],
                "num_parameters": 0,
            },
            {
                "name": "dense",
                "id": "dense",
                "class_name": "Dense",
                "output_shape": (None, 4),
                "num_parameters": 16,
            },
            {
                "name": "dense_1",
                "id": "dense_1",
                "class_name": "Dense",
                "output_shape": (None, 5),
                "num_parameters": 25,
            },
            {
                "name": "dense_2",
                "id": "dense_2",
                "class_name": "Dense",
                "output_shape": (None, 6),
                "num_parameters": 36,
            },
        ],
        "edges": [
            ["dense_input", "dense"],
            ["dense", "dense_1"],
            ["dense_1", "dense_2"],
        ],
    }


@pytest.mark.skipif(sys.platform == "darwin", reason="Cannot convert a symbolic Tensor")
def test_keras_convert_model_non_sequential():
    # necessary to keep the names of the layers consistent
    K.clear_session()

    # example from the Keras docs
    main_input = Input(
        shape=(100,),
        dtype="int32",
        name="main_input",
    )
    x = Embedding(
        output_dim=512,
        input_dim=10000,
        input_length=100,
    )(main_input)
    lstm_out = LSTM(32)(x)
    auxiliary_output = Dense(
        1,
        activation="sigmoid",
        name="aux_output",
    )(lstm_out)
    auxiliary_input = Input(
        shape=(5,),
        name="aux_input",
    )
    x = Concatenate()([lstm_out, auxiliary_input])
    x = Dense(64, activation="relu")(x)
    x = Dense(64, activation="relu")(x)
    x = Dense(64, activation="relu")(x)
    main_output = Dense(
        1,
        activation="sigmoid",
        name="main_output",
    )(x)
    model = Model(
        inputs=[main_input, auxiliary_input], outputs=[main_output, auxiliary_output]
    )
    wandb_model = wandb.data_types.Graph.from_keras(model)
    wandb_model_out = wandb.Graph._to_graph_json(wandb_model)

    print(wandb_model_out["edges"])
    assert wandb_model_out["nodes"][0] == {
        "name": "main_input",
        "id": "main_input",
        "class_name": "InputLayer",
        "output_shape": [(None, 100)],
        "num_parameters": 0,
    }
    assert wandb_model_out["edges"] == [
        ["main_input", "embedding"],
        ["embedding", "lstm"],
        ["lstm", "concatenate"],
        ["aux_input", "concatenate"],
        ["concatenate", "dense"],
        ["dense", "dense_1"],
        ["dense_1", "dense_2"],
        ["dense_2", "main_output"],
        ["lstm", "aux_output"],
    ]
