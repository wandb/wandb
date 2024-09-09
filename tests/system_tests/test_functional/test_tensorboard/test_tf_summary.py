"""Test that the TensorFlow summary API works with W&B.
Used https://www.tensorflow.org/api_docs/python/tf/summary as reference."""

import pytest
import tensorboard.summary.v1 as tensorboard_summary_v1
import tensorflow as tf
import wandb
from wandb.errors import term


def test_histogram(wandb_init, relay_server):
    with relay_server() as relay:
        with wandb_init(sync_tensorboard=True) as run:
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

        run_ids = relay.context.get_run_ids()
        assert len(run_ids) == 1
        assert run.id == run_ids[0]

        summary = relay.context.get_run_summary(run.id)
        assert summary["global_step"] == 4
        assert summary["activations"]["_type"] == "histogram"
        assert summary["initial_weights"]["_type"] == "histogram"

    wandb.tensorboard.unpatch()


def test_image(wandb_init, relay_server):
    with relay_server() as relay:
        with wandb_init(sync_tensorboard=True) as run:
            with tf.summary.create_file_writer("test/logs").as_default():
                for i in range(5):
                    image1 = tf.random.uniform(shape=[8, 8, 3])
                    tf.summary.image("multi_channel_image", [image1], step=i)
                    image2 = tf.random.uniform(shape=[8, 8, 1])
                    tf.summary.image("grayscale_image", [image2], step=i)

        run_ids = relay.context.get_run_ids()
        assert len(run_ids) == 1
        assert run.id == run_ids[0]

        summary = relay.context.get_run_summary(run.id)
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


def test_scalar(wandb_init, relay_server):
    with relay_server() as relay:
        scalars = [0.345, 0.234, 0.123]
        with wandb_init(sync_tensorboard=True) as run:
            with tf.summary.create_file_writer("test/logs").as_default():
                for i, scalar in enumerate(scalars):
                    tf.summary.scalar("loss", scalar, step=i)

        run_ids = relay.context.get_run_ids()
        assert len(run_ids) == 1
        assert run.id == run_ids[0]

        summary = relay.context.get_run_summary(run.id)
        assert summary["global_step"] == 2
        assert summary["loss"] == pytest.approx(scalars[-1])

        history = relay.context.get_run_history(run.id)
        assert len(history) == 3
        assert history["loss"].tolist() == pytest.approx(scalars)

    wandb.tensorboard.unpatch()


def test_pr_curves(relay_server, wandb_init):
    with relay_server() as relay, wandb_init(sync_tensorboard=True) as run:
        writer = tf.summary.create_file_writer("test/logs")
        with writer.as_default():
            tf.summary.experimental.write_raw_pb(
                tensorboard_summary_v1.pr_curve(
                    "test_pr",
                    labels=tf.constant([True, False, True]),
                    predictions=tf.constant([0.7, 0.2, 0.3]),
                    num_thresholds=5,
                ),
                step=0,
            )

    config = relay.context.config[run.id]
    assert "test_pr/pr_curves" in config["_wandb"]["value"]["visualize"]
    wandb.tensorboard.unpatch()


def test_compat_tensorboard(relay_server, wandb_init):
    # Parenthesized context managers which result in better formatting
    # are supported starting Python 3.10.
    # fmt: off
    with relay_server() as relay, \
         wandb_init(sync_tensorboard=True) as run, \
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

    run_ids = relay.context.get_run_ids()
    assert len(run_ids) == 1
    assert run.id == run_ids[0]

    summary = relay.context.get_run_summary(run.id)
    assert summary["global_step"] == 9
    assert "x_scalar_1" in summary

    history = relay.context.get_run_history(run.id)
    assert len(history) == 10

    wandb.tensorboard.unpatch()


def test_tb_sync_with_explicit_step_and_log(wandb_init, relay_server):
    with relay_server() as relay:
        with wandb_init(sync_tensorboard=True) as run:
            with tf.summary.create_file_writer(
                "test/logs",
            ).as_default():
                for i in range(10):
                    tf.summary.scalar(
                        "x_scalar",
                        tf.constant(i**2),
                        step=i,
                    )
            run.log({"y_scalar": 1337}, step=42)

    assert "Step cannot be set when using tensorboard syncing" in "".join(
        term.PRINTED_MESSAGES
    )
    history = relay.context.get_run_history(run.id)
    assert len(history) == 11
    assert history["x_scalar"].dropna().tolist() == [i**2 for i in range(10)]
    assert history["y_scalar"].dropna().tolist() == [1337]

    summary = relay.context.get_run_summary(run.id)
    assert summary["global_step"] == 9
    assert summary["x_scalar"] == 81
    assert summary["y_scalar"] == 1337

    telemetry = relay.context.get_run_telemetry(run.id)
    assert 35 in telemetry["3"]  # sync_tensorboard

    wandb.tensorboard.unpatch()
