"""Based on examples from https://www.tensorflow.org/api_docs/python/tf/keras/callbacks/TensorBoard
Test that the Keras TensorBoard callback works with W&B.
"""

import keras
import numpy as np
import pandas as pd
import pytest
import tensorflow as tf
import wandb


class MyModel(keras.Model):
    def build(self, _):
        self.dense = keras.layers.Dense(10)

    def call(self, x):
        outputs = self.dense(x)
        tf.summary.histogram("outputs", outputs)
        return outputs


@pytest.mark.wandb_core_only
def test_tb_callback(wandb_init, wandb_backend_spy):
    np.random.seed(42)

    with wandb_init(sync_tensorboard=True) as run:
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
        history_df = pd.DataFrame.from_dict(history, orient="index")
        # assert that there are 10 non-nan epoch_loss values
        assert len(history_df["epoch_loss"].dropna()) == 10

        assert summary["global_step"] == 9

        for tag in ["epoch_loss", "epoch_learning_rate"]:
            assert tag in summary

        for tag in ["kernel/histogram", "bias/histogram"]:
            assert summary[tag]["_type"] == "histogram"
            assert len(history_df[tag].dropna()) == 2

        for tag in ["kernel/image", "bias/image"]:
            assert summary[tag]["_type"] == "images/separated"
            assert len(history_df[tag].dropna()) == 2

        config = snapshot.config(run_id=run.id)
        telemetry = config["_wandb"]["value"]["t"]
        assert 35 in telemetry["3"]  # tensorboard_sync

    wandb.tensorboard.unpatch()
