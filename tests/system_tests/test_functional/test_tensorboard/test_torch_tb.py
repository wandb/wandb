"""Based on the docs: https://pytorch.org/docs/stable/tensorboard.html#torch.utils.tensorboard.writer.SummaryWriter

This test is to check if the tensorboard data is being processed correctly and sent to W&B.
"""

import numpy as np
import pytest
import torch
import wandb
from torch.utils.tensorboard import SummaryWriter


def test_add_scalar(wandb_init, relay_server):
    """Test adding a scalar to TensorBoard and syncing it to W&B."""

    with relay_server() as relay:
        with wandb_init(sync_tensorboard=True), SummaryWriter() as writer:
            for i in range(100):
                writer.add_scalar("y=2x", i * 2, i)

        run_ids = relay.context.get_run_ids()
        assert len(run_ids) == 1
        run_id = run_ids[0]

        summary = relay.context.get_run_summary(run_id)
        assert summary["global_step"] == 99
        assert summary["y=2x"] == 99 * 2

        history = relay.context.get_run_history(run_id)
        assert len(history) == 100

        telemetry = relay.context.get_run_telemetry(run_id)
        assert 35 in telemetry["3"]  # tensorboard_sync

    wandb.tensorboard.unpatch()


def test_add_scalars(wandb_init, relay_server):
    """Test adding multiple scalars to TensorBoard and syncing it to W&B."""
    with relay_server() as relay:
        with wandb_init(sync_tensorboard=True), SummaryWriter() as writer:
            r = 5
            for i in range(10):
                writer.add_scalars(
                    "run_14h",
                    {
                        "xsinx": np.sin(i / r),
                        "xcosx": np.cos(i / r),
                        "tanx": np.tan(i / r),
                    },
                    i,
                )

        run_ids = relay.context.get_run_ids()
        assert len(run_ids) == 1
        run_id = run_ids[0]

        summary = relay.context.get_run_summary(run_id)
        assert summary["run_14h_xsinx"] == pytest.approx(np.sin(9 / r))
        assert summary["run_14h_xsinx/global_step"] == 9
        assert summary["run_14h_xcosx"] == pytest.approx(np.cos(9 / r))
        assert summary["run_14h_xcosx/global_step"] == 9
        assert summary["run_14h_tanx"] == pytest.approx(np.tan(9 / r))
        assert summary["run_14h_tanx/global_step"] == 9

        telemetry = relay.context.get_run_telemetry(run_id)
        assert 35 in telemetry["3"]  # tensorboard_sync

    wandb.tensorboard.unpatch()


def test_add_image(wandb_init, relay_server):
    """Test adding an image to TensorBoard and syncing it to W&B."""
    with relay_server() as relay:
        with wandb_init(tensorboard=True), SummaryWriter() as writer:
            for i in range(10):
                writer.add_image(
                    "example",
                    torch.randint(0, 256, (3, 28, 28), dtype=torch.uint8),
                    i + 1,
                )

        run_ids = relay.context.get_run_ids()
        assert len(run_ids) == 1
        run_id = run_ids[0]

        summary = relay.context.get_run_summary(run_id)
        assert summary["global_step"] == 10

        assert summary["example"]["_type"] == "images/separated"
        assert summary["example"]["width"] == 28
        assert summary["example"]["height"] == 28
        assert summary["example"]["format"] == "png"

        telemetry = relay.context.get_run_telemetry(run_id)
        assert 35 in telemetry["3"]  # tensorboard_sync

    wandb.tensorboard.unpatch()


def test_add_images(wandb_init, relay_server):
    """Test adding multiple images to TensorBoard and syncing it to W&B."""
    with relay_server() as relay:
        with wandb_init(sync_tensorboard=True), SummaryWriter() as writer:
            img_batch = np.zeros((16, 3, 100, 100))
            for i in range(16):
                img_batch[i, 0] = np.arange(0, 10000).reshape(100, 100) / 10000 / 16 * i
                img_batch[i, 1] = (
                    (1 - np.arange(0, 10000).reshape(100, 100) / 10000) / 16 * i
                )
            writer.add_images("my_image_batch", img_batch, 0)

        run_ids = relay.context.get_run_ids()
        assert len(run_ids) == 1
        run_id = run_ids[0]

        summary = relay.context.get_run_summary(run_id)
        assert summary["global_step"] == 0
        assert summary["my_image_batch"]["_type"] == "images/separated"
        assert summary["my_image_batch"]["width"] == 800
        assert summary["my_image_batch"]["height"] == 200
        assert summary["my_image_batch"]["count"] == 1
        assert summary["my_image_batch"]["format"] == "png"

        telemetry = relay.context.get_run_telemetry(run_id)
        assert 35 in telemetry["3"]  # tensorboard_sync
    wandb.tensorboard.unpatch()


def test_add_histogram(wandb_init, relay_server):
    """Test adding a histogram to TensorBoard and syncing it to W&B."""
    with relay_server() as relay:
        with wandb_init(sync_tensorboard=True), SummaryWriter() as writer:
            for i in range(10):
                x = np.random.random(1000)
                writer.add_histogram("distribution centers", x + i, i)

        run_ids = relay.context.get_run_ids()
        assert len(run_ids) == 1
        run_id = run_ids[0]

        summary = relay.context.get_run_summary(run_id)
        assert summary["global_step"] == 9
        assert summary["distribution centers"]["_type"] == "histogram"

        telemetry = relay.context.get_run_telemetry(run_id)
        assert 35 in telemetry["3"]  # tensorboard_sync

    wandb.tensorboard.unpatch()


def test_add_histogram_raw(wandb_init, relay_server):
    """Test adding a histogram with raw data to TensorBoard and syncing it to W&B."""
    with relay_server() as relay:
        with wandb_init(sync_tensorboard=True), SummaryWriter() as writer:
            dummy_data = []
            for idx, value in enumerate(range(50)):
                dummy_data += [idx + 0.001] * value

            bins = list(range(50 + 2))
            bins = np.array(bins)
            values = np.array(dummy_data).astype(float).reshape(-1)
            counts, limits = np.histogram(values, bins=bins)
            sum_sq = values.dot(values)
            writer.add_histogram_raw(
                tag="histogram_with_raw_data",
                min=values.min(),
                max=values.max(),
                num=len(values),
                sum=values.sum(),
                sum_squares=sum_sq,
                bucket_limits=limits[1:].tolist(),
                bucket_counts=counts.tolist(),
                global_step=0,
            )

        run_ids = relay.context.get_run_ids()
        assert len(run_ids) == 1
        run_id = run_ids[0]

        summary = relay.context.get_run_summary(run_id)
        assert summary["global_step"] == 0
        assert summary["histogram_with_raw_data"]["_type"] == "histogram"
        assert len(summary["histogram_with_raw_data"]["values"]) == 49
        assert len(summary["histogram_with_raw_data"]["bins"]) == 50

    wandb.tensorboard.unpatch()


def test_add_pr_curve(wandb_init, relay_server):
    """Test adding a precision-recall curve to TensorBoard and syncing it to W&B."""
    with relay_server() as relay:
        with wandb_init(sync_tensorboard=True), SummaryWriter() as writer:
            labels = np.random.randint(2, size=100)  # binary label
            predictions = np.random.rand(100)
            writer.add_pr_curve("pr_curve", labels, predictions, 0)

        run_ids = relay.context.get_run_ids()
        assert len(run_ids) == 1
        run_id = run_ids[0]

        summary = relay.context.get_run_summary(run_id)
        assert summary["pr_curve_table"]["_type"] == "table-file"
        assert summary["pr_curve_table"]["ncols"] == 2

        telemetry = relay.context.get_run_telemetry(run_id)
        assert 35 in telemetry["3"]  # tensorboard_sync

    wandb.tensorboard.unpatch()
