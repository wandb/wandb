"""Based on examples from https://www.tensorflow.org/api_docs/python/tf/keras/callbacks/TensorBoard
Test that the Keras TensorBoard callback works with W&B.
"""

import keras
import numpy as np
import tensorflow as tf
import wandb
from tests.fixtures.wandb_backend_spy import WandbBackendSpy


class MyModel(keras.Model):
    def build(self, _):
        self.dense = keras.layers.Dense(10)

    def call(self, x):
        outputs = self.dense(x)
        tf.summary.histogram("outputs", outputs)
        return outputs


def test_tb_callback(wandb_backend_spy: WandbBackendSpy):
    np.random.seed(42)

    with wandb.init(sync_tensorboard=True) as run:
        model = MyModel()
        model.compile("sgd", "mse")

        x = np.random.rand(100, 28)
        y = np.random.rand(100, 10)
        train_rows = 80

        tb_callback = keras.callbacks.TensorBoard(write_images=True, histogram_freq=5)
        model.fit(
            x[:train_rows, :],
            y[:train_rows, :],
            validation_data=(x[train_rows:, :], y[train_rows:, :]),
            epochs=10,
            callbacks=[tb_callback],
        )

    with wandb_backend_spy.freeze() as snapshot:
        assert len(snapshot.run_ids()) == 1

        summary = snapshot.summary(run_id=run.id)
        history = snapshot.history(run_id=run.id)

        train_step_count = 0
        validation_step_count = 0
        for value in history.values():
            if "train/epoch_loss" in value:
                train_step_count += 1
            if "validation/epoch_loss" in value:
                validation_step_count += 1
        assert train_step_count == 10
        assert validation_step_count == 10

        assert summary["global_step"] == 9

        for tag in [
            "train/epoch_loss",
            "train/epoch_learning_rate",
            "validation/epoch_loss",
        ]:
            assert tag in summary

        for tag in [
            "train/my_model/dense/kernel/histogram",
            "train/my_model/dense/bias/histogram",
        ]:
            assert tag in summary
            assert summary[tag]["_type"] == "histogram"

            items_with_tag = list(step for step, item in history.items() if tag in item)
            assert len(items_with_tag) == 2

        for tag in [
            "train/my_model/dense/kernel/image",
            "train/my_model/dense/bias/image",
        ]:
            assert tag in summary
            assert summary[tag]["_type"] == "images/separated"

            items_with_tag = list(step for step, item in history.items() if tag in item)
            assert len(items_with_tag) == 2

        telemetry = snapshot.telemetry(run_id=run.id)
        assert 35 in telemetry["3"]  # tensorboard_sync
