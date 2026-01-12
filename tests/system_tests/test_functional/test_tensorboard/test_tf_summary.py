"""Test that the TensorFlow summary API works with W&B.
Used https://www.tensorflow.org/api_docs/python/tf/summary as reference."""

from __future__ import annotations

import os

import numpy as np
import pytest
import tensorboard.plugins.pr_curve.summary as pr_curve_plugins_summary
import tensorboard.summary.v1 as tensorboard_summary_v1
import tensorflow as tf
import wandb

PR_CURVE_SPEC = {
    "panel_type": "Vega2",
    "panel_config": {
        "fieldSettings": {"x": "recall", "y": "precision"},
        "panelDefId": "wandb/line/v0",
        "stringSettings": {"title": "test_pr/pr_curves Precision v. Recall"},
        "transform": {"name": "tableWithLeafColNames"},
        "userQuery": {
            "queryFields": [
                {
                    "name": "runSets",
                    "args": [{"name": "runSets", "value": "${runSets}"}],
                    "fields": [
                        {"name": "id"},
                        {"name": "name"},
                        {"name": "_defaultColorIndex"},
                        {
                            "name": "summaryTable",
                            "args": [
                                {"name": "tableKey", "value": "test_pr/pr_curves"}
                            ],
                        },
                    ],
                }
            ]
        },
    },
}


def test_histogram(wandb_backend_spy):
    with wandb.init(sync_tensorboard=True) as run:
        w = tf.summary.create_file_writer("test/logs")

        with w.as_default():
            for i in range(5):
                tf.summary.histogram(
                    "activations", tf.random.uniform([100, 50]), step=i
                )
                tf.summary.histogram(
                    "initial_weights", tf.random.normal([1000]), step=i
                )
        w.close()

    with wandb_backend_spy.freeze() as snapshot:
        assert len(snapshot.run_ids()) == 1

        summary = snapshot.summary(run_id=run.id)
        assert summary["global_step"] == 4
        assert summary["activations"]["_type"] == "histogram"
        assert summary["initial_weights"]["_type"] == "histogram"

    wandb.tensorboard.unpatch()


def test_image(wandb_backend_spy):
    with wandb.init(sync_tensorboard=True) as run:
        with tf.summary.create_file_writer("test/logs").as_default():
            for i in range(5):
                image1 = tf.random.uniform(shape=[8, 8, 3])
                tf.summary.image("multi_channel_image", [image1], step=i)
                image2 = tf.random.uniform(shape=[8, 8, 1])
                tf.summary.image("grayscale_image", [image2], step=i)

    with wandb_backend_spy.freeze() as snapshot:
        assert len(snapshot.run_ids()) == 1

        summary = snapshot.summary(run_id=run.id)
        assert summary["global_step"] == 4

        assert summary["multi_channel_image"]["_type"] == "images/separated"
        assert summary["multi_channel_image"]["width"] == 8
        assert summary["multi_channel_image"]["height"] == 8
        assert summary["multi_channel_image"]["format"] == "png"

        assert summary["grayscale_image"]["_type"] == "images/separated"
        assert summary["grayscale_image"]["width"] == 8
        assert summary["grayscale_image"]["height"] == 8
        assert summary["grayscale_image"]["format"] == "png"

    wandb.tensorboard.unpatch()


def test_batch_images(wandb_backend_spy):
    with wandb.init(sync_tensorboard=True) as run:
        with tf.summary.create_file_writer("test/logs").as_default():
            # tensor shape: (number_of_images, image_height, image_width, channels)
            img_tensor = np.random.rand(5, 15, 10, 3)
            tf.summary.image("Training data", img_tensor, max_outputs=5, step=0)

    with wandb_backend_spy.freeze() as snapshot:
        assert len(snapshot.run_ids()) == 1

        summary = snapshot.summary(run_id=run.id)

        assert summary["global_step"] == 0

        assert "Training data" in summary
        assert summary["Training data"]["_type"] == "images/separated"
        assert summary["Training data"]["height"] == 15
        assert summary["Training data"]["width"] == 10
        assert summary["Training data"]["count"] == 5
        for file_name in summary["Training data"]["filenames"]:
            assert os.path.exists(f"{run.dir}/{file_name}")

    wandb.tensorboard.unpatch()


def test_scalar(wandb_backend_spy):
    scalars = [0.345, 0.234, 0.123]
    with wandb.init(sync_tensorboard=True) as run:
        with tf.summary.create_file_writer("test/logs").as_default():
            for i, scalar in enumerate(scalars):
                tf.summary.scalar("loss", scalar, step=i)

    with wandb_backend_spy.freeze() as snapshot:
        assert len(snapshot.run_ids()) == 1

        summary = snapshot.summary(run_id=run.id)
        assert summary["global_step"] == 2
        assert summary["loss"] == pytest.approx(scalars[-1])

        history = snapshot.history(run_id=run.id)

        assert len(history) == 3

        for step in history:
            # Using the summary writer through tensorboard there is some floating point precision loss.
            # So we use pytest.approx to compare the values.
            assert history[step]["loss"] == pytest.approx(scalars[step])

    wandb.tensorboard.unpatch()


def test_add_pr_curve(wandb_backend_spy):
    with wandb.init(sync_tensorboard=True) as run:
        with tf.summary.create_file_writer("test/logs").as_default():
            tf.summary.experimental.write_raw_pb(
                tensorboard_summary_v1.pr_curve(
                    "test_pr",
                    labels=tf.constant(
                        [True, False, True],
                    ),
                    predictions=tf.constant(
                        [0.7, 0.2, 0.3],
                    ),
                    num_thresholds=5,
                ),
                step=0,
            )

    with wandb_backend_spy.freeze() as snapshot:
        config = snapshot.config(run_id=run.id)
        assert (
            config["_wandb"]["value"]["visualize"]["test_pr/pr_curves"] == PR_CURVE_SPEC
        )
    wandb.tensorboard.unpatch()


def test_add_pr_curve_plugin(wandb_backend_spy):
    with wandb.init(sync_tensorboard=True) as run:
        with tf.compat.v1.Session() as sess:
            with tf.compat.v1.summary.FileWriter("test/logs", session=sess) as writer:
                summary = tf.compat.v1.summary.merge(
                    [
                        pr_curve_plugins_summary.op(
                            name="test_pr",
                            labels=tf.constant(
                                [True, False, True],
                            ),
                            predictions=tf.constant(
                                [0.7, 0.2, 0.3],
                            ),
                            num_thresholds=5,
                        )
                    ]
                )
                writer.add_summary(sess.run(summary), 0)

    with wandb_backend_spy.freeze() as snapshot:
        config = snapshot.config(run_id=run.id)
        assert (
            config["_wandb"]["value"]["visualize"]["test_pr/pr_curves"] == PR_CURVE_SPEC
        )

        summary = snapshot.summary(run_id=run.id)
        assert summary["global_step"] == 0
        assert summary["test_pr/pr_curves"]["_type"] == "table-file"

    wandb.tensorboard.unpatch()


def test_compat_tensorboard(wandb_backend_spy):
    # Parenthesized context managers which result in better formatting
    # are supported starting Python 3.10.
    # fmt: off
    with wandb.init(sync_tensorboard=True) as run, \
         tf.compat.v1.Session(graph=tf.compat.v1.Graph()) as sess:
        # fmt: on

        x_scalar = tf.compat.v1.get_variable(
            "x_scalar",
            shape=[],
            initializer=tf.compat.v1.truncated_normal_initializer(
                mean=0,
                stddev=1,
            ),
        )
        init = tf.compat.v1.global_variables_initializer()
        summary = tf.compat.v1.summary.scalar(
            "x_scalar",
            x_scalar,
        )
        with tf.compat.v1.summary.FileWriter("test/logs", sess.graph) as writer:
            for step in range(10):
                sess.run(init)
                writer.add_summary(
                    sess.run(summary),
                    step,
                )

    with wandb_backend_spy.freeze() as snapshot:
        assert len(snapshot.run_ids()) == 1

        summary = snapshot.summary(run_id=run.id)
        assert summary["global_step"] == 9
        assert "x_scalar_1" in summary

        history = snapshot.history(run_id=run.id)
        assert len(history) == 10

    wandb.tensorboard.unpatch()


def test_tb_sync_with_explicit_step_and_log(
    wandb_backend_spy,
    mock_wandb_log,
):
    with wandb.init(sync_tensorboard=True) as run:
        with tf.summary.create_file_writer(
            "test/logs",
        ).as_default():
            tf.summary.scalar(
                "x_scalar",
                tf.constant(1),
                step=1,
            )
        run.log({"y_scalar": 1337}, step=42)

    with wandb_backend_spy.freeze() as snapshot:
        mock_wandb_log.assert_warned(
            "Step cannot be set when using tensorboard syncing"
        )
        history = snapshot.history(run_id=run.id)
        assert len(history) == 2

        for item in history.values():
            if "x_scalar" in item:
                assert item["x_scalar"] == 1
            else:
                assert item["y_scalar"] == 1337

        telemetry = snapshot.telemetry(run_id=run.id)
        assert 35 in telemetry["3"]  # sync_tensorboard

    wandb.tensorboard.unpatch()
