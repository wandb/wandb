import pytest

pytest.importorskip("wandb_core")
tf = pytest.importorskip("tensorflow")


def create_model():
    return tf.keras.models.Sequential(
        [
            tf.keras.layers.Flatten(input_shape=(28, 28)),
            tf.keras.layers.Dense(512, activation="relu"),
            tf.keras.layers.Dropout(0.2),
            tf.keras.layers.Dense(10, activation="softmax"),
        ]
    )


@pytest.mark.skip(reason="flaky test, depends on an external service")
def test_sync_tensorboard(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init(sync_tensorboard=True)

        mnist = tf.keras.datasets.mnist

        (x_train, y_train), (x_test, y_test) = mnist.load_data()
        x_train, x_test = x_train / 255.0, x_test / 255.0

        model = create_model()
        model.compile(
            optimizer="adam",
            loss="sparse_categorical_crossentropy",
            metrics=["accuracy"],
        )

        tensorboard_callback = tf.keras.callbacks.TensorBoard(histogram_freq=1)

        model.fit(
            x=x_train,
            y=y_train,
            # epochs=5,
            epochs=1,
            validation_data=(x_test, y_test),
            callbacks=[tensorboard_callback],
        )

        run.finish()

        uploaded_files = relay.context.get_run_uploaded_files(run.id)
        print(uploaded_files)
        assert any("events.out.tfevents" in f for f in uploaded_files)
