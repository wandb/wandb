"""Based on examples from https://www.tensorflow.org/api_docs/python/tf/keras/callbacks/TensorBoard
Test that the Keras TensorBoard callback works with W&B.
"""

from __future__ import annotations

import keras
import numpy as np
import tensorflow as tf
import wandb


class MyModel(keras.Model):
    def build(self, _):
        self.dense = keras.layers.Dense(10)

    def call(self, x):
        outputs = self.dense(x)
        tf.summary.histogram("outputs", outputs)
        return outputs


def test_tb_callback(wandb_backend_spy):
    np.random.seed(42)

    with wandb.init(sync_tensorboard=True) as run:
        model = MyModel()
        model.compile("sgd", "mse")

        x_train = np.random.rand(100, 28)
        y_train = np.random.rand(100, 10)

        tb_callback = keras.callbacks.TensorBoard(write_images=True, histogram_freq=5)
        model.fit(
            x_train,
            y_train,
            epochs=10,
            callbacks=[tb_callback],
        )

    with wandb_backend_spy.freeze() as snapshot:
        assert len(snapshot.run_ids()) == 1

        summary = snapshot.summary(run_id=run.id)
        history = snapshot.history(run_id=run.id)
        assert (
            len(list(step for step, item in history.items() if "epoch_loss" in item))
            == 10
        )

        assert summary["global_step"] == 9

        for tag in ["epoch_loss", "epoch_learning_rate"]:
            assert tag in summary

        for tag in ["kernel/histogram", "bias/histogram"]:
            assert summary[tag]["_type"] == "histogram"

            items_with_tag = list(step for step, item in history.items() if tag in item)
            assert len(items_with_tag) == 2

        for tag in ["kernel/image", "bias/image"]:
            assert summary[tag]["_type"] == "images/separated"

            items_with_tag = list(step for step, item in history.items() if tag in item)
            assert len(items_with_tag) == 2

        telemetry = snapshot.telemetry(run_id=run.id)
        assert 35 in telemetry["3"]  # tensorboard_sync

    wandb.tensorboard.unpatch()
