"""Tests for the `reinit` setting."""

from __future__ import annotations

import pytest
import wandb


def test_reinit_create_new__does_not_modify_wandb_run():
    with wandb.init(mode="offline", reinit="create_new"):
        assert wandb.run is None


def test_reinit_default__controls_wandb_run():
    with wandb.init(mode="offline") as run:
        assert wandb.run is run

    assert wandb.run is None


@pytest.mark.parametrize("finish_previous", (True, "finish_previous"))
def test_reinit_finish_previous(finish_previous):
    run1 = wandb.init(mode="offline")
    run2 = wandb.init(mode="offline", reinit="create_new")

    wandb.init(mode="offline", reinit=finish_previous)

    # NOTE: There is no public way to check if a run is finished.
    assert run1._is_finished
    assert run2._is_finished


@pytest.mark.parametrize("return_previous", (False, "return_previous"))
def test_reinit_return_previous(return_previous):
    wandb.init(mode="offline")
    run2 = wandb.init(mode="offline", reinit="create_new")
    run3 = wandb.init(mode="offline", reinit="create_new")

    run3.finish()
    previous = wandb.init(mode="offline", reinit=return_previous)

    # run2 is returned because it is the most recent unfinished run.
    assert previous is run2
