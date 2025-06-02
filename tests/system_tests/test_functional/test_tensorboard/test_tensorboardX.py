"""Tests for tensorboardX integration."""

import torch
import wandb
from tensorboardX import SummaryWriter


def test_add_scalar(wandb_backend_spy):
    with wandb.init(sync_tensorboard=True) as run:
        with SummaryWriter() as writer:
            for i in range(10):
                writer.add_scalar("loss", torch.tensor(i / 64), i + 1)

    with wandb_backend_spy.freeze() as snapshot:
        assert len(snapshot.run_ids()) == 1

        summary = snapshot.summary(run_id=run.id)
        assert summary["global_step"] == 10
        assert summary["loss"] == 9 / 64

    wandb.tensorboard.unpatch()


def test_add_image(wandb_backend_spy):
    with wandb.init(sync_tensorboard=True) as run:
        with SummaryWriter() as writer:
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

    wandb.tensorboard.unpatch()


def test_add_gif(wandb_backend_spy):
    with wandb.init(sync_tensorboard=True) as run:
        with SummaryWriter() as writer:
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
