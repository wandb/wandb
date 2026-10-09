"""Tests for wandb.tensorflow.WandbHook."""

import tensorflow as tf
import wandb
from tensorboard.compat.proto import summary_pb2


def test_tensorflow_hook(wandb_backend_spy):
    """Integration test for TensorFlow hook."""
    with wandb.init() as run:
        with tf.Graph().as_default():
            tf.compat.v1.train.get_or_create_global_step()
            const_1 = tf.constant(42)
            tf.compat.v1.summary.scalar("const_1", const_1)
            summary_op = tf.compat.v1.summary.merge_all()

            with tf.compat.v1.train.MonitoredTrainingSession(
                hooks=[wandb.tensorflow.WandbHook(summary_op, steps_per_log=1)]
            ) as sess:
                summary1, _ = sess.run([summary_op, const_1])

        with tf.Graph().as_default():
            tf.compat.v1.train.get_or_create_global_step()
            const_2 = tf.constant(23)
            tf.compat.v1.summary.scalar("const_2", const_2)
            summary_op = tf.compat.v1.summary.merge_all()

            with tf.compat.v1.train.MonitoredTrainingSession(
                hooks=[wandb.tensorflow.WandbHook(summary_op, steps_per_log=1)]
            ) as sess:
                summary2, _ = sess.run([summary_op, const_2])

    with wandb_backend_spy.freeze() as snapshot:
        history = snapshot.history(run_id=run.id)
        assert history[0]["const_1"] == 42.0
        assert history[0]["const_2"] == 23.0

    # test digesting encoded summary
    assert wandb.tensorboard.tf_summary_to_dict(summary1) == {"const_1": 42.0}

    # test digesting a list of encoded summaries
    assert wandb.tensorboard.tf_summary_to_dict(
        summary_pb2.Summary().ParseFromString(summary1)
    ) == {"const_1": 42.0}

    # test digesting a list of encoded summaries
    assert wandb.tensorboard.tf_summary_to_dict([summary1, summary2]) == {
        "const_1": 42.0,
        "const_2": 23.0,
    }
