"""Based on the docs: https://pytorch.org/docs/stable/tensorboard.html#torch.utils.tensorboard.writer.SummaryWriter

This test is to check if the tensorboard data is being processed correctly and sent to W&B.
"""

from __future__ import annotations

import numpy as np
import pytest
import torch
import wandb
from torch.utils.tensorboard import SummaryWriter


@pytest.mark.skip(reason="hangs on processing tensorboard data")
def test_add_scalar(wandb_backend_spy):
    """Test adding a scalar to TensorBoard and syncing it to W&B."""

    with wandb.init(sync_tensorboard=True) as run, SummaryWriter() as writer:
        for i in range(100):
            writer.add_scalar("y=2x", i * 2, i)

    with wandb_backend_spy.freeze() as snapshot:
        assert len(snapshot.run_ids()) == 1

        summary = snapshot.summary(run_id=run.id)
        assert summary["global_step"] == 99
        assert summary["y=2x"] == 99 * 2

        history = snapshot.history(run_id=run.id)
        assert len(history) == 100

        telemetry = snapshot.telemetry(run_id=run.id)
        assert 35 in telemetry["3"]  # tensorboard_sync

    wandb.tensorboard.unpatch()


def test_add_scalars(wandb_backend_spy):
    """Test adding multiple scalars to TensorBoard and syncing it to W&B."""
    with wandb.init(sync_tensorboard=True) as run, SummaryWriter() as writer:
        for i in range(10):
            writer.add_scalars(
                "value",
                {
                    "one": 1.1,
                    "two": 2.2,
                },
                i,
            )

    with wandb_backend_spy.freeze() as snapshot:
        assert len(snapshot.run_ids()) == 1

        summary = snapshot.summary(run_id=run.id)
        assert summary["value_one/value"] == pytest.approx(1.1)
        assert summary["value_one/global_step"] == 9
        assert summary["value_two/value"] == pytest.approx(2.2)
        assert summary["value_two/global_step"] == 9

        telemetry = snapshot.telemetry(run_id=run.id)
        assert 35 in telemetry["3"]  # tensorboard_sync

    wandb.tensorboard.unpatch()


def test_add_image(wandb_backend_spy):
    """Test adding an image to TensorBoard and syncing it to W&B."""
    with wandb.init(sync_tensorboard=True) as run, SummaryWriter() as writer:
        for i in range(10):
            writer.add_image(
                "example",
                torch.randint(0, 256, (3, 28, 28), dtype=torch.uint8),
                i + 1,
            )

    with wandb_backend_spy.freeze() as snapshot:
        assert len(snapshot.run_ids()) == 1

        summary = snapshot.summary(run_id=run.id)
        assert summary["global_step"] == 10

        assert summary["example"]["_type"] == "images/separated"
        assert summary["example"]["width"] == 28
        assert summary["example"]["height"] == 28
        assert summary["example"]["format"] == "png"

        telemetry = snapshot.telemetry(run_id=run.id)
        assert 35 in telemetry["3"]  # tensorboard_sync

    wandb.tensorboard.unpatch()


def test_add_gif(wandb_backend_spy):
    with wandb.init(sync_tensorboard=True) as run, SummaryWriter() as writer:
        for i in range(10):
            writer.add_video(
                "example",
                # add video takes a tensor of shape (N, T, C, H, W)
                # N = Batch size, T = Number of frames, C = Number of channels, H = Height, W = Width,
                torch.randint(0, 256, (1, 1, 3, 1, 1), dtype=torch.uint8),
                i + 1,
            )

    with wandb_backend_spy.freeze() as snapshot:
        assert len(snapshot.run_ids()) == 1

        summary = snapshot.summary(run_id=run.id)
        assert summary["global_step"] == 10
        assert summary["example"]["_type"] == "images/separated"
        assert summary["example"]["width"] == 1
        assert summary["example"]["height"] == 1
        assert summary["example"]["format"] == "gif"

    wandb.tensorboard.unpatch()


def test_add_images(wandb_backend_spy):
    """Test adding multiple images to TensorBoard and syncing it to W&B."""
    with wandb.init(sync_tensorboard=True) as run, SummaryWriter() as writer:
        img_batch = np.zeros((16, 3, 100, 100))
        for i in range(16):
            img_batch[i, 0] = np.arange(0, 10000).reshape(100, 100) / 10000 / 16 * i
            img_batch[i, 1] = (
                (1 - np.arange(0, 10000).reshape(100, 100) / 10000) / 16 * i
            )
        writer.add_images("my_image_batch", img_batch, 0)

    with wandb_backend_spy.freeze() as snapshot:
        assert len(snapshot.run_ids()) == 1

        summary = snapshot.summary(run_id=run.id)
        assert summary["global_step"] == 0
        assert summary["my_image_batch"]["_type"] == "images/separated"
        assert summary["my_image_batch"]["width"] == 800
        assert summary["my_image_batch"]["height"] == 200
        assert summary["my_image_batch"]["count"] == 1
        assert summary["my_image_batch"]["format"] == "png"

        telemetry = snapshot.telemetry(run_id=run.id)
        assert 35 in telemetry["3"]  # tensorboard_sync

    wandb.tensorboard.unpatch()


def test_add_histogram(wandb_backend_spy):
    """Test adding a histogram to TensorBoard and syncing it to W&B."""
    with wandb.init(sync_tensorboard=True) as run, SummaryWriter() as writer:
        writer.add_histogram(
            "distribution centers",
            1 + np.random.random(1000),
            global_step=4,
            bins=500,
        )

    with wandb_backend_spy.freeze() as snapshot:
        assert len(snapshot.run_ids()) == 1

        summary = snapshot.summary(run_id=run.id)
        assert summary["global_step"] == 4
        assert summary["distribution centers"]["_type"] == "histogram"
        assert len(summary["distribution centers"]["values"]) == 500

        telemetry = snapshot.telemetry(run_id=run.id)
        assert 35 in telemetry["3"]  # tensorboard_sync

    wandb.tensorboard.unpatch()


@pytest.mark.skip(reason="old style TensorBoard not implemented")
def test_add_pr_curve(wandb_backend_spy):
    """Test adding a precision-recall curve to TensorBoard and syncing it to W&B."""
    with wandb.init(sync_tensorboard=True) as run, SummaryWriter() as writer:
        labels = np.random.randint(2, size=100)  # binary label
        predictions = np.random.rand(100)
        writer.add_pr_curve("pr_curve", labels, predictions, 0)

    with wandb_backend_spy.freeze() as snapshot:
        assert len(snapshot.run_ids()) == 1

        summary = snapshot.summary(run_id=run.id)
        assert summary["pr_curve_table"]["_type"] == "table-file"
        assert summary["pr_curve_table"]["ncols"] == 2

        telemetry = snapshot.telemetry(run_id=run.id)
        assert 35 in telemetry["3"]  # tensorboard_sync

    wandb.tensorboard.unpatch()


def test_add_pr_curve_wandb_core(wandb_backend_spy):
    """Test adding a precision-recall curve to TensorBoard and syncing it to W&B."""
    with wandb.init(sync_tensorboard=True) as run, SummaryWriter() as writer:
        labels = np.random.randint(2, size=100)  # binary label
        predictions = np.random.rand(100)
        writer.add_pr_curve("pr_curve", labels, predictions, 0)

    with wandb_backend_spy.freeze() as snapshot:
        assert len(snapshot.run_ids()) == 1

        summary = snapshot.summary(run_id=run.id)
        assert summary["pr_curve"]["_type"] == "table-file"
        assert summary["pr_curve"]["ncols"] == 2

        telemetry = snapshot.telemetry(run_id=run.id)
        assert 35 in telemetry["3"]  # tensorboard_sync

    wandb.tensorboard.unpatch()
