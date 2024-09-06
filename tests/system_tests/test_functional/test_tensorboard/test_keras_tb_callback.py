"""Based on examples from https://www.tensorflow.org/api_docs/python/tf/keras/callbacks/TensorBoard
Test that the Keras TensorBoard callback works with W&B.
"""

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


def test_tb_callback(relay_server, wandb_init):
    with relay_server() as relay:
        with wandb.init(sync_tensorboard=True):
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
        assert len(history) == 10

        for tag in ["global_step", "train/global_step"]:
            assert summary[tag] == 9

        for tag in ["train/epoch_loss", "train/epoch_learning_rate"]:
            assert tag in summary

        for tag in ["train/kernel/histogram", "train/bias/histogram"]:
            assert summary[tag]["_type"] == "histogram"
            assert history[tag].dropna().index.tolist() == [0, 5]

        for tag in ["train/kernel_image", "train/bias_image"]:
            assert summary[tag]["_type"] == "images/separated"
            assert history[tag].dropna().index.tolist() == [0, 5]

        telemetry = relay.context.get_run_telemetry(run_id)
        assert 35 in telemetry["3"]

    wandb.tensorboard.unpatch()
