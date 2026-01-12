"""Tests for wandb.tensorboard.log and wandb.tensorboard.WandbHook."""

from __future__ import annotations

import pytest
import tensorflow as tf
import wandb
from tensorboard.compat.proto import summary_pb2


def test_wandb_tf_log(wandb_backend_spy, assets_path):
    with wandb.init(sync_tensorboard=True) as run:
        summary_pb = open(assets_path("wandb_tensorflow_summary.pb"), "rb").read()
        wandb.tensorboard.log(summary_pb)

    with wandb_backend_spy.freeze() as snapshot:
        assert len(snapshot.run_ids()) == 1

        summary = snapshot.summary(run_id=run.id)
        for tag in [
            "layer1/activations",
            "layer1/biases/summaries/histogram",
            "layer1/weights/summaries/histogram",
            "layer2/Wx_plus_b/pre_activations",
            "layer2/activations",
            "layer2/biases/summaries/histogram",
            "layer2/weights/summaries/histogram",
            "layer1/Wx_plus_b/pre_activations",
        ]:
            assert summary[tag]["_type"] == "histogram"

        for tag, value in [
            ("accuracy_1", 0.8799999952316284),
            ("cross_entropy_1", 0.37727174162864685),
            ("dropout/dropout_keep_probability", 0.8999999761581421),
            ("layer1/biases/summaries/max", 0.12949132919311523),
            ("layer1/biases/summaries/mean", 0.10085226595401764),
            ("layer1/biases/summaries/min", 0.0768924281001091),
            ("layer1/biases/summaries/stddev_1", 0.01017912570387125),
            ("layer1/weights/summaries/max", 0.22247056663036346),
            ("layer1/weights/summaries/mean", 0.00014527945313602686),
            ("layer1/weights/summaries/min", -0.22323597967624664),
            ("layer1/weights/summaries/stddev_1", 0.08832632750272751),
            ("layer2/biases/summaries/max", 0.11211398988962173),
            ("layer2/biases/summaries/mean", 0.09975100308656693),
            ("layer2/biases/summaries/min", 0.0904880091547966),
            ("layer2/biases/summaries/stddev_1", 0.006791393272578716),
            ("layer2/weights/summaries/max", 0.21537037193775177),
            ("layer2/weights/summaries/mean", -0.0023455708287656307),
            ("layer2/weights/summaries/min", -0.22206202149391174),
            ("layer2/weights/summaries/stddev_1", 0.08973880857229233),
        ]:
            assert summary[tag] == value

        assert summary["input_reshape_input_image"]["_type"] == "images/separated"
        assert summary["input_reshape_input_image"]["count"] == 10

        telemetry = snapshot.telemetry(run_id=run.id)
        assert 29 in telemetry["3"]  # wandb.tensorflow.log


def test_no_init_error(assets_path):
    with pytest.raises(
        wandb.Error,
        match=r"You must call `wandb.init\(\)` before calling `wandb.tensorflow.log`",
    ):
        summary_pb = open(assets_path("wandb_tensorflow_summary.pb"), "rb").read()
        wandb.tensorboard.log(summary_pb)


@pytest.mark.skipif(tf.__version__ >= "2.16.0", reason="tf.estimator is not supported")
def test_tensorflow_hook():
    """Integration test for TensorFlow hook."""

    with tf.Graph().as_default():
        tf.compat.v1.train.get_or_create_global_step()
        const_1 = tf.constant(42)
        tf.compat.v1.summary.scalar("const_1", const_1)
        summary_op = tf.compat.v1.summary.merge_all()

        with tf.compat.v1.train.MonitoredTrainingSession()(
            hooks=[wandb.tensorflow.WandbHook(summary_op, steps_per_log=1)]
        ) as sess:
            summary1, _ = sess.run([summary_op, const_1])

    with tf.Graph().as_default():
        tf.compat.v1.train.get_or_create_global_step()
        const_2 = tf.constant(23)
        tf.compat.v1.summary.scalar("const_2", const_2)
        summary_op = tf.compat.v1.summary.merge_all()

        with tf.compat.v1.train.MonitoredTrainingSession()(
            hooks=[wandb.tensorflow.WandbHook(summary_op, steps_per_log=1)]
        ) as sess:
            summary2, _ = sess.run([summary_op, const_2])

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
