#!/usr/bin/env python

import pprint

import os
import json
import sys
import platform
import pytest

if sys.version_info >= (3, 9):
    pytest.importorskip("tensorflow")
from tensorboard.plugins.pr_curve import summary as pr_curve_plugin_summary
import tensorboard.summary.v1 as tb_summary
import tensorflow as tf
import wandb
from wandb.errors import term
from wandb import wandb_sdk


THIS_DIR = os.path.dirname(os.path.abspath(__file__))
SUMMARY_PB_FILENAME = os.path.join(THIS_DIR, "wandb_tensorflow_summary.pb")
SUMMARY_PB = open(SUMMARY_PB_FILENAME, "rb").read()
PR_CURVE_PANEL_CONFIG = {
    "panel_type": "Vega2",
    "panel_config": {
        "userQuery": {
            "queryFields": [
                {
                    "name": "runSets",
                    "args": [{"name": "runSets", "value": "${runSets}"}],
                    "fields": [
                        {"name": "id", "fields": []},
                        {"name": "name", "fields": []},
                        {"name": "_defaultColorIndex", "fields": []},
                        {
                            "name": "summaryTable",
                            "args": [
                                {"name": "tableKey", "value": "test_pr/pr_curves_table"}
                            ],
                            "fields": [],
                        },
                    ],
                }
            ]
        },
        "panelDefId": "wandb/line/v0",
        "transform": {"name": "tableWithLeafColNames"},
        "fieldSettings": {"x": "recall", "y": "precision"},
        "stringSettings": {"title": "Precision v. Recall"},
    },
}


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


@pytest.mark.skipif(
    platform.system() == "Windows" or sys.version_info < (3, 5),
    reason="TF has sketchy support for py2.  TODO: Windows is legitimately busted",
)
def test_compat_tensorboard(live_mock_server, test_settings):
    # TODO(jhr): does not work with --flake-finder
    # TODO: we currently don't unpatch tensorflow so this is the only test that can do it...
    wandb.init(sync_tensorboard=True, settings=test_settings)

    with tf.compat.v1.Session() as sess:
        initializer = tf.compat.v1.truncated_normal_initializer(mean=0, stddev=1)
        x_scalar = tf.compat.v1.get_variable(
            "x_scalar", shape=[], initializer=initializer
        )
        x_summary = tf.compat.v1.summary.scalar("x_scalar", x_scalar)
        init = tf.compat.v1.global_variables_initializer()
        writer = tf.compat.v1.summary.FileWriter(
            os.path.join(".", "summary"), sess.graph
        )
        for step in range(10):
            sess.run(init)
            summary = sess.run(x_summary)
            writer.add_summary(summary, step)
        writer.close()
    wandb.finish()
    server_ctx = live_mock_server.get_ctx()
    print("CONTEXT!", server_ctx)
    first_stream_hist = server_ctx["file_stream"][-2]["files"]["wandb-history.jsonl"]
    print(first_stream_hist)
    assert json.loads(first_stream_hist["content"][-1])["_step"] == 9
    assert json.loads(first_stream_hist["content"][-1])["global_step"] == 9
    assert (
        "\x1b[34m\x1b[1mwandb\x1b[0m: \x1b[33mWARNING\x1b[0m Step cannot be set when using"
        " syncing with tensorboard. Please log your step values as a metric such as 'global_step'"
    ) not in term.PRINTED_MESSAGES
    wandb.tensorboard.unpatch()


@pytest.mark.skipif(
    platform.system() == "Windows" or sys.version_info < (3, 5),
    reason="TF has sketchy support for py2.  TODO: Windows is legitimately busted",
)
def test_tensorboard_log_with_wandb_log(live_mock_server, test_settings, parse_ctx):
    wandb.init(sync_tensorboard=True, settings=test_settings)

    with tf.compat.v1.Session() as sess:
        initializer = tf.compat.v1.truncated_normal_initializer(mean=0, stddev=1)
        y_scalar = tf.compat.v1.get_variable(
            "y_scalar", shape=[], initializer=initializer
        )
        x_summary = tf.compat.v1.summary.scalar("y_scalar", y_scalar)
        init = tf.compat.v1.global_variables_initializer()
        writer = tf.compat.v1.summary.FileWriter(
            os.path.join(".", "summary"), sess.graph
        )
        for step in range(10):
            sess.run(init)
            summary = sess.run(x_summary)
            writer.add_summary(summary, step)
            wandb.log({"wandb_logged_val": step ** 2})

        wandb.log({"wandb_logged_val_with_step": step}, step=step + 3)
        writer.close()
    wandb.finish()
    server_ctx = live_mock_server.get_ctx()
    print("CONTEXT!", server_ctx)
    ctx_util = parse_ctx(live_mock_server.get_ctx())
    history = ctx_util.history
    assert (
        "\x1b[34m\x1b[1mwandb\x1b[0m: \x1b[33mWARNING\x1b[0m Step cannot be set when"
        " using syncing with tensorboard. Please log your step values as a metric such as 'global_step'"
    ) in term.PRINTED_MESSAGES
    assert history[9]["wandb_logged_val"] == 81
    assert history[10]["wandb_logged_val_with_step"] == 9
    assert history[-1]["_step"] == 20
    wandb.tensorboard.unpatch()


@pytest.mark.skipif(
    platform.system() == "Windows" or sys.version_info < (3, 5),
    reason="TF has sketchy support for py2.  TODO: Windows is legitimately busted",
)
def test_add_pr_curve(live_mock_server, test_settings):
    wandb.init(sync_tensorboard=True, settings=test_settings)
    writer = tf.summary.create_file_writer(wandb.run.dir)
    pr_curve_summary = tb_summary.pr_curve(
        "test_pr",
        labels=tf.constant([True, False, True]),
        predictions=tf.constant([0.7, 0.2, 0.3]),
        num_thresholds=5,
    )

    with writer.as_default():
        tf.summary.experimental.write_raw_pb(pr_curve_summary, step=0)

    wandb.finish()
    server_ctx = live_mock_server.get_ctx()

    assert (
        "test_pr/pr_curves"
        in server_ctx["config"][-1]["_wandb"]["value"]["visualize"].keys()
    )
    assert (
        server_ctx["config"][-1]["_wandb"]["value"]["visualize"]["test_pr/pr_curves"]
        == PR_CURVE_PANEL_CONFIG
    )
    wandb.tensorboard.unpatch()


@pytest.mark.skipif(
    platform.system() == "Windows" or sys.version_info < (3, 5),
    reason="TF has sketchy support for py2.  TODO: Windows is legitimately busted",
)
def test_add_pr_curve_plugin(live_mock_server, test_settings):
    tf.compat.v1.disable_v2_behavior()
    wandb.init(sync_tensorboard=True, settings=test_settings)
    summ_op = pr_curve_plugin_summary.op(
        name="test_pr",
        labels=tf.constant([True, False, True]),
        predictions=tf.constant([0.7, 0.2, 0.3]),
        num_thresholds=5,
    )
    merged_summary_op = tf.compat.v1.summary.merge([summ_op])
    sess = tf.compat.v1.Session()
    writer = tf.compat.v1.summary.FileWriter(wandb.run.dir, sess.graph)

    merged_summary = sess.run(merged_summary_op)
    writer.add_summary(merged_summary, 0)
    writer.close()

    wandb.finish()
    server_ctx = live_mock_server.get_ctx()

    assert (
        "test_pr/pr_curves"
        in server_ctx["config"][-1]["_wandb"]["value"]["visualize"].keys()
    )
    assert (
        server_ctx["config"][-1]["_wandb"]["value"]["visualize"]["test_pr/pr_curves"]
        == PR_CURVE_PANEL_CONFIG
    )
    wandb.tensorboard.unpatch()
