#!/usr/bin/env python
import os
import json
import platform
import pytest

from tensorboard.plugins.pr_curve import summary as pr_curve_plugin_summary
import tensorboard.summary.v1 as tb_summary
import tensorflow as tf
import wandb
from wandb.errors import term
from tests import utils


SUMMARY_PB_FILENAME = utils.assets_path("wandb_tensorflow_summary.pb")
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
        "stringSettings": {"title": "test_pr/pr_curves Precision v. Recall"},
    },
}


@pytest.mark.skipif(
    platform.system() == "Windows",
    reason="TODO: Windows is legitimately busted",
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
    filtered = list(
        filter(
            lambda resp: "files" in resp and "wandb-history.jsonl" in resp["files"],
            server_ctx["file_stream"],
        )
    )
    first_stream_hist = filtered[-1]["files"]["wandb-history.jsonl"]
    print(first_stream_hist)
    assert json.loads(first_stream_hist["content"][-1])["_step"] == 9
    assert json.loads(first_stream_hist["content"][-1])["global_step"] == 9
    assert (
        "\x1b[34m\x1b[1mwandb\x1b[0m: \x1b[33mWARNING\x1b[0m Step cannot be set when using"
        " syncing with tensorboard. Please log your step values as a metric such as 'global_step'"
    ) not in term.PRINTED_MESSAGES
    wandb.tensorboard.unpatch()


@pytest.mark.skipif(
    platform.system() == "Windows",
    reason="TODO: Windows is legitimately busted",
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
            wandb.log({"wandb_logged_val": step**2})

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
    assert all("_runtime" in step for step in history)
    assert history[9]["wandb_logged_val"] == 81
    assert history[10]["wandb_logged_val_with_step"] == 9
    assert history[-1]["_step"] == 20
    wandb.tensorboard.unpatch()


@pytest.mark.skipif(
    platform.system() == "Windows",
    reason="TODO: Windows is legitimately busted",
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
    platform.system() == "Windows",
    reason="TODO: Windows is legitimately busted",
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


def test_tensorflow_log_error():

    with pytest.raises(wandb.Error) as excinfo:
        wandb.tensorboard.log(SUMMARY_PB)

        assert (
            "You must call `wandb.init()` before calling wandb.tensorflow.log"
            in str(excinfo.value)
        )
