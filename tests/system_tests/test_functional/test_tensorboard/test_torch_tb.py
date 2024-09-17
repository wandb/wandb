"""Based on the docs: https://pytorch.org/docs/stable/tensorboard.html#torch.utils.tensorboard.writer.SummaryWriter

This test is to check if the tensorboard data is being processed correctly and sent to W&B.
"""

import numpy as np
import pytest
import torch
import wandb
from torch.utils.tensorboard import SummaryWriter


@pytest.mark.skip_wandb_core(
    feature="tensorboard", reason="hangs on processing tensorboard data"
)
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
            for i in range(10):
                writer.add_scalars(
                    "value",
                    {
                        "one": 1.1,
                        "two": 2.2,
                    },
                    i,
                )

        run_ids = relay.context.get_run_ids()
        assert len(run_ids) == 1
        run_id = run_ids[0]

        summary = relay.context.get_run_summary(run_id)
        assert summary["value_one/value"] == pytest.approx(1.1)
        assert summary["value_one/global_step"] == 9
        assert summary["value_two/value"] == pytest.approx(2.2)
        assert summary["value_two/global_step"] == 9

        telemetry = relay.context.get_run_telemetry(run_id)
        assert 35 in telemetry["3"]  # tensorboard_sync

    wandb.tensorboard.unpatch()


@pytest.mark.skip_wandb_core(
    feature="tensorboard", reason="missing implementation of old style TensorBoard"
)
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


@pytest.mark.skip_wandb_core(
    feature="tensorboard",
    reason="hangs on processing data and missing implementation of old style TensorBoard",
)
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
            writer.add_histogram(
                "distribution centers",
                1 + np.random.random(1000),
                global_step=4,
                bins=500,
            )

        run_ids = relay.context.get_run_ids()
        assert len(run_ids) == 1
        run_id = run_ids[0]

        summary = relay.context.get_run_summary(run_id)
        assert summary["global_step"] == 4
        assert summary["distribution centers"]["_type"] == "histogram"
        assert len(summary["distribution centers"]["values"]) == 500

        telemetry = relay.context.get_run_telemetry(run_id)
        assert 35 in telemetry["3"]  # tensorboard_sync

    wandb.tensorboard.unpatch()


@pytest.mark.skip_wandb_core(
    feature="tensorboard", reason="old style TensorBoard not implemented"
)
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
