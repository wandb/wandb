"""Based on examples from https://www.tensorflow.org/api_docs/python/tf/keras/callbacks/TensorBoard
Test that the Keras TensorBoard callback works with W&B.
"""

import keras
import numpy as np
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
def test_tb_callback(relay_server, wandb_init):
    np.random.seed(42)

    with relay_server() as relay:
        with wandb_init(sync_tensorboard=True):
            model = MyModel()
            model.compile("sgd", "mse")

            x_train = np.random.rand(100, 28)
            y_train = np.random.rand(100, 10)

            tb_callback = keras.callbacks.TensorBoard(
                write_images=True, histogram_freq=5
            )
            model.fit(
                x_train,
                y_train,
                epochs=10,
                callbacks=[tb_callback],
            )

        run_ids = relay.context.get_run_ids()
        assert len(run_ids) == 1
        run_id = run_ids[0]

        summary = relay.context.get_run_summary(run_id)
        history = relay.context.get_run_history(run_id)
        # assert that there are 10 non-nan epoch_loss values
        assert len(history["epoch_loss"].dropna()) == 10

        assert summary["global_step"] == 9

        for tag in ["epoch_loss", "epoch_learning_rate"]:
            assert tag in summary

        for tag in ["kernel/histogram", "bias/histogram"]:
            assert summary[tag]["_type"] == "histogram"
            assert len(history[tag].dropna()) == 2

        for tag in ["kernel/image", "bias/image"]:
            assert summary[tag]["_type"] == "images/separated"
            assert len(history[tag].dropna()) == 2

        telemetry = relay.context.get_run_telemetry(run_id)
        assert 35 in telemetry["3"]

    wandb.tensorboard.unpatch()
