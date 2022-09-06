import glob
import json
import os

import pytest
import tensorflow as tf
from tensorflow.keras import backend as K  # noqa: N812
from tensorflow.keras.layers import Dense, Flatten, Reshape
from tensorflow.keras.models import Sequential
from wandb.keras import WandbCallback


@pytest.fixture
def dummy_model(request):
    K.clear_session()
    multi = request.node.get_closest_marker("multiclass")
    image_output = request.node.get_closest_marker("image_output")
    loss, nodes = (
        ("categorical_crossentropy", 10) if multi else ("binary_crossentropy", 1)
    )
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


def graph_json(run_dir, graph):
    path = os.path.join(run_dir, graph["path"])
    with open(path) as fh:
        return json.load(fh)


def test_basic_keras(dummy_model, dummy_data, relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init()
        run_dir, run_id = run.dir, run.id
        dummy_model.fit(
            *dummy_data,
            epochs=2,
            batch_size=36,
            callbacks=[
                WandbCallback(),
            ],
        )
        run.finish()

    history = relay.context.get_run_history(run_id)
    summary = relay.context.get_run_summary(run_id)

    assert history["epoch"][0] == 0
    assert len(graph_json(run_dir, summary["graph"])["nodes"]) == 3


def test_keras_telemetry(dummy_model, dummy_data, relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init()
        dummy_model.fit(
            *dummy_data,
            epochs=2,
            batch_size=36,
            callbacks=[
                WandbCallback(),
            ],
        )
        run.finish()

    telemetry = relay.context.get_run_telemetry(run.id)
    assert telemetry and 8 in telemetry.get("3", [])


def test_keras_telemetry_deprecated(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init()
        run_id = run.id
        # use deprecated argument data_type
        WandbCallback(
            data_type="image",
        )
        run.finish()

    telemetry = relay.context.get_run_telemetry(run_id)
    # TelemetryRecord field 10 is Deprecated,
    # whose filed 1 is keras_callback_data_type
    assert telemetry and 8 in telemetry.get("3", []) and 1 in telemetry.get("10", [])


def test_keras_image_binary(dummy_model, dummy_data, relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init()
        dummy_model.fit(
            *dummy_data,
            epochs=2,
            batch_size=36,
            validation_data=dummy_data,
            callbacks=[
                WandbCallback(data_type="image"),
            ],
        )
        run.finish()

    history = relay.context.get_run_history(run.id)
    assert len(history["examples"][0]["captions"]) == 36


def test_keras_image_binary_captions(dummy_model, dummy_data, relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init()
        dummy_model.fit(
            *dummy_data,
            epochs=2,
            batch_size=36,
            validation_data=dummy_data,
            callbacks=[
                WandbCallback(data_type="image", predictions=10, labels=["Rad", "Nice"])
            ],
        )
        run.finish()

    history = relay.context.get_run_history(run.id)
    assert history["examples"][0]["captions"][0] in ["Rad", "Nice"]


@pytest.mark.multiclass
def test_keras_image_multiclass(dummy_model, dummy_data, relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init()
        dummy_model.fit(
            *dummy_data,
            epochs=2,
            batch_size=36,
            validation_data=dummy_data,
            callbacks=[WandbCallback(data_type="image", predictions=10)],
        )
        run.finish()

    history = relay.context.get_run_history(run.id)
    assert len(history["examples"][0]["captions"]) == 10


@pytest.mark.multiclass
def test_keras_image_multiclass_captions(
    dummy_model, dummy_data, relay_server, wandb_init
):
    with relay_server() as relay:
        run = wandb_init()
        dummy_model.fit(
            *dummy_data,
            epochs=2,
            batch_size=36,
            validation_data=dummy_data,
            callbacks=[
                WandbCallback(
                    data_type="image",
                    predictions=10,
                    labels=[
                        "Rad",
                        "Nice",
                        "Fun",
                        "Rad",
                        "Nice",
                        "Fun",
                        "Rad",
                        "Nice",
                        "Fun",
                        "Rad",
                    ],
                )
            ],
        )
        run.finish()

    history = relay.context.get_run_history(run.id)
    assert history["examples"][0]["captions"][0] in [
        "Rad",
        "Nice",
        "Fun",
    ]


@pytest.mark.image_output
def test_keras_image_output(dummy_model, dummy_data, relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init()
        dummy_model.fit(
            *dummy_data,
            epochs=2,
            batch_size=36,
            validation_data=dummy_data,
            callbacks=[
                WandbCallback(
                    data_type="image",
                    predictions=10,
                ),
            ],
        )
        run.finish()

    history = relay.context.get_run_history(run.id)
    assert history["examples"][0]["count"] == 30
    assert history["examples"][0]["height"] == 10


def test_dataset_functional(relay_server, wandb_init):

    with relay_server() as relay:
        run = wandb_init()

        data = tf.data.Dataset.range(5).map(lambda x: (x, 1)).batch(1)
        inputs = tf.keras.Input(shape=(1,))
        outputs = tf.keras.layers.Dense(1)(inputs)

        model = tf.keras.Model(
            inputs=inputs,
            outputs=outputs,
        )
        model.compile(
            optimizer=tf.keras.optimizers.Adam(),
            loss="mse",
        )
        model.fit(
            data,
            callbacks=[
                WandbCallback(save_model=False),
            ],
        )

        run_dir = run.dir
        run.finish()

    summary = relay.context.get_run_summary(run.id)
    assert (
        graph_json(run_dir, summary["graph"])["nodes"][0]["class_name"] == "InputLayer"
    )


def test_keras_log_weights(dummy_model, dummy_data, relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init()
        dummy_model.fit(
            *dummy_data,
            epochs=2,
            batch_size=36,
            validation_data=dummy_data,
            callbacks=[
                WandbCallback(
                    data_type="image",
                    log_weights=True,
                ),
            ],
        )
        run.finish()

    history = relay.context.get_run_history(run.id)
    assert history["parameters/dense.weights"][0]["_type"] == "histogram"


def test_keras_log_gradients(dummy_model, dummy_data, relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init()
        dummy_model.fit(
            *dummy_data,
            epochs=2,
            batch_size=36,
            validation_data=dummy_data,
            callbacks=[
                WandbCallback(
                    data_type="image",
                    log_gradients=True,
                    training_data=dummy_data,
                )
            ],
        )
        run.finish()

    history = relay.context.get_run_history(run.id)
    assert history["gradients/dense/kernel.gradient"][0]["_type"] == "histogram"
    assert history["gradients/dense/bias.gradient"][0]["_type"] == "histogram"


def test_keras_save_model(dummy_model, dummy_data, wandb_init):
    run = wandb_init()
    dummy_model.fit(
        *dummy_data,
        epochs=2,
        batch_size=36,
        validation_data=dummy_data,
        callbacks=[
            WandbCallback(
                data_type="image",
                save_model=True,
            ),
        ],
    )
    run.finish()

    assert len(glob.glob(os.path.join(run.dir, "model-best.h5"))) == 1


@pytest.mark.timeout(300)
def test_keras_dsviz(dummy_model, dummy_data, wandb_init):
    run = wandb_init()
    dummy_model.fit(
        *dummy_data,
        epochs=2,
        batch_size=36,
        validation_data=dummy_data,
        callbacks=[
            WandbCallback(
                log_evaluation=True,
            ),
        ],
    )

    assert run.summary["validation_predictions"] is not None
    assert run.summary["validation_predictions"]["artifact_path"] is not None
    assert run.summary["validation_predictions"]["_type"] == "table-file"
    run.finish()
