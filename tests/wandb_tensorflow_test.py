#!/usr/bin/env python

import pprint

import os
import six
import sys
import pytest

if sys.version_info >= (3, 9):
    pytest.importorskip("tensorflow")
import tensorflow as tf
import wandb
from wandb import wandb_sdk


THIS_DIR = os.path.dirname(os.path.abspath(__file__))
SUMMARY_PB_FILENAME = os.path.join(THIS_DIR, "wandb_tensorflow_summary.pb")
SUMMARY_PB = open(SUMMARY_PB_FILENAME, "rb").read()

if hasattr(tf.summary, "merge_all"):
    tf_summary = tf.summary
else:
    tf_summary = tf.compat.v1.summary

if hasattr(tf.train, "MonitoredTrainingSession"):
    MonitoredTrainingSession = tf.train.MonitoredTrainingSession
else:
    MonitoredTrainingSession = tf.compat.v1.train.MonitoredTrainingSession

if hasattr(tf.train, "get_or_create_global_step"):
    get_or_create_global_step = tf.train.get_or_create_global_step
else:
    get_or_create_global_step = tf.compat.v1.train.get_or_create_global_step


def test_tf_log(mocked_run):
    history = wandb_sdk.History(mocked_run)
    summaries_logged = []

    def spy_cb(row, step=None):
        summaries_logged.append(row)

    history._set_callback(spy_cb)

    wandb.tensorboard.log(SUMMARY_PB, history=history)
    history.add({})  # Flush the previous row.
    assert len(summaries_logged) == 1
    summary = summaries_logged[0]
    print(summary)

    images = summary["input_reshape_input_image"]
    del summary["input_reshape_input_image"]
    histo_keys = [
        "layer1/activations",
        "layer1/biases/summaries/histogram",
        "layer1/weights/summaries/histogram",
        "layer2/Wx_plus_b/pre_activations",
        "layer2/activations",
        "layer2/biases/summaries/histogram",
        "layer2/weights/summaries/histogram",
        "layer1/Wx_plus_b/pre_activations",
    ]
    histos = [summary[k] for k in histo_keys]
    for k in histo_keys:
        del summary[k]

    pprint.pprint(summary)

    assert len(images) == 10
    assert all(isinstance(img, wandb.Image) for img in images)
    assert all(isinstance(hist, wandb.Histogram) for hist in histos)
    assert summary == {
        "_step": 0,
        "_runtime": summary["_runtime"],
        "_timestamp": summary["_timestamp"],
        "accuracy_1": 0.8799999952316284,
        "cross_entropy_1": 0.37727174162864685,
        "dropout/dropout_keep_probability": 0.8999999761581421,
        "layer1/biases/summaries/max": 0.12949132919311523,
        "layer1/biases/summaries/mean": 0.10085226595401764,
        "layer1/biases/summaries/min": 0.0768924281001091,
        "layer1/biases/summaries/stddev_1": 0.01017912570387125,
        "layer1/weights/summaries/max": 0.22247056663036346,
        "layer1/weights/summaries/mean": 0.00014527945313602686,
        "layer1/weights/summaries/min": -0.22323597967624664,
        "layer1/weights/summaries/stddev_1": 0.08832632750272751,
        "layer2/biases/summaries/max": 0.11211398988962173,
        "layer2/biases/summaries/mean": 0.09975100308656693,
        "layer2/biases/summaries/min": 0.0904880091547966,
        "layer2/biases/summaries/stddev_1": 0.006791393272578716,
        "layer2/weights/summaries/max": 0.21537037193775177,
        "layer2/weights/summaries/mean": -0.0023455708287656307,
        "layer2/weights/summaries/min": -0.22206202149391174,
        "layer2/weights/summaries/stddev_1": 0.08973880857229233,
    }


def test_hook(mocked_run):
    history = wandb_sdk.History(mocked_run)
    summaries_logged = []

    def spy_cb(row, step=None):
        summaries_logged.append(row)

    history._set_callback(spy_cb)

    g1 = tf.Graph()
    with g1.as_default():
        get_or_create_global_step()
        c1 = tf.constant(42)
        tf_summary.scalar("c1", c1)
        summary_op = tf_summary.merge_all()

        hook = wandb.tensorflow.WandbHook(summary_op, history=history, steps_per_log=1)
        with MonitoredTrainingSession(hooks=[hook]) as sess:
            summary, acc = sess.run([summary_op, c1])
        history.add({})  # Flush the previous row.

    assert wandb.tensorboard.tf_summary_to_dict(summary) == {"c1": 42.0}
    assert summaries_logged[0]["c1"] == 42.0
