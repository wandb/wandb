import os
import platform

import pytest
import tensorboard.summary.v1 as tb_summary
import tensorflow as tf
import wandb
from tensorboard.plugins.pr_curve import summary as pr_curve_plugin_summary
from wandb.errors import term

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
def test_compat_tensorboard(relay_server, wandb_init):
    # TODO(jhr): does not work with --flake-finder
    # TODO: we currently don't unpatch tensorflow so this is the only test that can do it...
    with relay_server() as relay:
        run = wandb_init(sync_tensorboard=True)
        run_id = run.id
        with tf.compat.v1.Session() as sess:
            initializer = tf.compat.v1.truncated_normal_initializer(
                mean=0,
                stddev=1,
            )
            x_scalar = tf.compat.v1.get_variable(
                "x_scalar",
                shape=[],
                initializer=initializer,
            )
            x_summary = tf.compat.v1.summary.scalar(
                "x_scalar",
                x_scalar,
            )
            init = tf.compat.v1.global_variables_initializer()
            writer = tf.compat.v1.summary.FileWriter(
                os.path.join(".", "summary"), sess.graph
            )
            for step in range(10):
                sess.run(init)
                summary = sess.run(x_summary)
                writer.add_summary(summary, step)
            writer.close()
        run.finish()

    history = relay.context.get_run_history(run_id, include_private=True)
    assert history["_step"].values[-1] == 9
    assert history["global_step"].values[-1] == 9

    assert (
        "\x1b[34m\x1b[1mwandb\x1b[0m: \x1b[33mWARNING\x1b[0m Step cannot be set when using"
        " syncing with tensorboard. Please log your step values as a metric such as 'global_step'"
    ) not in term.PRINTED_MESSAGES
    wandb.tensorboard.unpatch()


@pytest.mark.skipif(
    platform.system() == "Windows",
    reason="TODO: Windows is legitimately busted",
)
def test_tensorboard_log_with_wandb_log(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init(sync_tensorboard=True)
        run_id = run.id
        with tf.compat.v1.Session() as sess:
            initializer = tf.compat.v1.truncated_normal_initializer(
                mean=0,
                stddev=1,
            )
            y_scalar = tf.compat.v1.get_variable(
                "y_scalar",
                shape=[],
                initializer=initializer,
            )
            x_summary = tf.compat.v1.summary.scalar(
                "y_scalar",
                y_scalar,
            )
            init = tf.compat.v1.global_variables_initializer()
            writer = tf.compat.v1.summary.FileWriter(
                os.path.join(".", "summary"),
                sess.graph,
            )
            for step in range(10):
                sess.run(init)
                summary = sess.run(x_summary)
                writer.add_summary(summary, step)
                run.log(
                    {"wandb_logged_val": step**2},
                )

            run.log(
                {"wandb_logged_val_with_step": step},
                step=step + 3,
            )
            writer.close()
        run.finish()

    history = relay.context.get_run_history(run_id, include_private=True)
    assert (
        "\x1b[34m\x1b[1mwandb\x1b[0m: \x1b[33mWARNING\x1b[0m Step cannot be set when"
        " using syncing with tensorboard. Please log your step values as a metric such as 'global_step'"
    ) in term.PRINTED_MESSAGES

    assert history["wandb_logged_val"][9] == 81
    assert history["wandb_logged_val_with_step"][10] == 9
    assert all(history["_runtime"])
    assert history["_step"].values[-1] == 20
    wandb.tensorboard.unpatch()


@pytest.mark.skipif(
    platform.system() == "Windows",
    reason="TODO: Windows is legitimately busted",
)
def test_add_pr_curve(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init(sync_tensorboard=True)
        writer = tf.summary.create_file_writer(run.dir)
        pr_curve_summary = tb_summary.pr_curve(
            "test_pr",
            labels=tf.constant(
                [True, False, True],
            ),
            predictions=tf.constant(
                [0.7, 0.2, 0.3],
            ),
            num_thresholds=5,
        )

        with writer.as_default():
            tf.summary.experimental.write_raw_pb(
                pr_curve_summary,
                step=0,
            )

        run.finish()

    config = relay.context.config[run.id]
    assert "test_pr/pr_curves" in config["_wandb"]["value"]["visualize"]
    assert (
        config["_wandb"]["value"]["visualize"]["test_pr/pr_curves"]
        == PR_CURVE_PANEL_CONFIG
    )
    wandb.tensorboard.unpatch()


@pytest.mark.skipif(
    platform.system() == "Windows",
    reason="TODO: Windows is legitimately busted",
)
def test_add_pr_curve_plugin(relay_server, wandb_init):
    tf.compat.v1.disable_v2_behavior()
    with relay_server() as relay:
        run = wandb_init(sync_tensorboard=True)
        summ_op = pr_curve_plugin_summary.op(
            name="test_pr",
            labels=tf.constant(
                [True, False, True],
            ),
            predictions=tf.constant(
                [0.7, 0.2, 0.3],
            ),
            num_thresholds=5,
        )
        merged_summary_op = tf.compat.v1.summary.merge([summ_op])
        sess = tf.compat.v1.Session()
        writer = tf.compat.v1.summary.FileWriter(run.dir, sess.graph)

        merged_summary = sess.run(merged_summary_op)
        writer.add_summary(merged_summary, 0)
        writer.close()

        run.finish()

    config = relay.context.config[run.id]
    assert "test_pr/pr_curves" in config["_wandb"]["value"]["visualize"]
    assert (
        config["_wandb"]["value"]["visualize"]["test_pr/pr_curves"]
        == PR_CURVE_PANEL_CONFIG
    )
    wandb.tensorboard.unpatch()


def test_tensorflow_log_error(assets_path):
    summary_pb_filename = assets_path("wandb_tensorflow_summary.pb")
    summary_pb = open(summary_pb_filename, "rb").read()

    with pytest.raises(
        wandb.Error,
        match=r"You must call `wandb.init\(\)` before calling `wandb.tensorflow.log`",
    ):
        wandb.tensorboard.log(summary_pb)
