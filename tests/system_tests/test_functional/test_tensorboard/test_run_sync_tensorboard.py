import pathlib

import pytest
import tensorflow as tf
import wandb
from tests.fixtures.wandb_backend_spy import WandbBackendSpy


def test_syncing(wandb_backend_spy: WandbBackendSpy):
    with wandb.init() as run:
        # On Windows, this tests that forward slashes become backslashes
        # or that forward slashes work fine.
        run.sync_tensorboard("my/tb/logs", namespace="test", save_to=None)
        with tf.summary.create_file_writer("my/tb/logs").as_default():
            tf.summary.scalar("x", 0, step=0)
            tf.summary.scalar("x", 1, step=1)

    with wandb_backend_spy.freeze() as snapshot:
        history = snapshot.history(run_id=run.id)
        assert "test/x" in history[0] and history[0]["test/x"] == 0
        assert "test/x" in history[1] and history[1]["test/x"] == 1


def test_syncing_existing_files(wandb_backend_spy: WandbBackendSpy):
    with tf.summary.create_file_writer("my/tb/logs").as_default():
        tf.summary.scalar("x", 0, step=0)
        tf.summary.scalar("x", 1, step=1)
    with tf.summary.create_file_writer("my/tb/logs").as_default():
        tf.summary.scalar("x", 2, step=2)
        tf.summary.scalar("x", 3, step=3)

    with wandb.init() as run:
        run.sync_tensorboard("my/tb/logs", save_to="", existing_files=True)

    with wandb_backend_spy.freeze() as snapshot:
        # Check that all files were parsed.
        history = snapshot.history(run_id=run.id)
        for i in range(4):
            assert "x" in history[i] and history[i]["x"] == i

        # Check that all files were uploaded.
        files = snapshot.uploaded_files(run_id=run.id)
        assert len([f for f in files if "tfevents" in f]) == 2


@pytest.mark.parametrize(
    "save_to,expected",
    (
        pytest.param(None, None, id="none"),
        pytest.param("", ".", id="empty"),
        pytest.param("some/folder", "some/folder", id="relative"),
        pytest.param("..weird", "..weird", id="..weird"),
    ),
)
def test_syncing_save_to(
    wandb_backend_spy: WandbBackendSpy,
    save_to: str | None,
    expected: str | None,
):
    with wandb.init() as run:
        run.sync_tensorboard("my/tb/logs", save_to=save_to)
        with tf.summary.create_file_writer("my/tb/logs").as_default():
            tf.summary.scalar("x", 321, step=0)

    with wandb_backend_spy.freeze() as snapshot:
        files = snapshot.uploaded_files(run_id=run.id)

        for file in files:
            path = pathlib.PurePath(file)
            if path.parent.as_posix() == expected and "tfevents" in path.name:
                found = file
                break
        else:
            found = None

        assert bool(found) == bool(expected), files


def test_syncing_save_to__absolute_path():
    with wandb.init(mode="offline") as run:
        with pytest.raises(
            wandb.UsageError,
            match="save_to must be relative",
        ):
            run.sync_tensorboard(
                "my/tb/logs",
                save_to=pathlib.Path(".").absolute(),
            )


def test_syncing_save_to__nonlocal_path():
    with wandb.init(mode="offline") as run:
        with pytest.raises(
            wandb.UsageError,
            match=r"save_to cannot use \.\.",
        ):
            run.sync_tensorboard(
                "my/tb/logs",
                save_to="valid/../still_ok/../../nevermind",
            )
