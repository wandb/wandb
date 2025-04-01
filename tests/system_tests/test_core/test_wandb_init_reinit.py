"""Tests for the `reinit` setting."""

import pytest
import wandb


def test_reinit_allow__wandb_run_is_set():
    run1 = wandb.init(mode="offline")

    with wandb.init(mode="offline", reinit="allow"):
        assert wandb.run is run1

    # Finishing the second run does not reset wandb.run to None.
    assert wandb.run is run1


def test_wandb_run_becomes_none_if_finished():
    run1 = wandb.init(mode="offline")
    wandb.init(mode="offline", reinit="allow")

    assert wandb.run is run1
    run1.finish()

    # Finishing run1 does not set wandb.run to the second run.
    assert wandb.run is None


def test_reinit_allow__wandb_run_is_none():
    run1 = wandb.init(mode="offline")
    wandb.init(mode="offline", reinit="allow")
    run1.finish()

    assert wandb.run is None
    run3 = wandb.init(mode="offline", reinit="allow")

    # Since wandb.run was None, it becomes set to run3.
    # wandb.run does not becomes the second run despite it being active.
    assert wandb.run is run3


@pytest.mark.parametrize("finish_previous", (True, "finish_previous"))
def test_reinit_finish_previous(finish_previous):
    run1 = wandb.init(mode="offline")
    run2 = wandb.init(mode="offline", reinit="allow")

    wandb.init(mode="offline", reinit=finish_previous)

    # NOTE: There is no public way to check if a run is finished.
    assert run1._is_finished
    assert run2._is_finished


@pytest.mark.parametrize("return_previous", (False, "return_previous"))
def test_reinit_return_previous(return_previous):
    wandb.init(mode="offline")
    run2 = wandb.init(mode="offline", reinit="allow")
    run3 = wandb.init(mode="offline", reinit="allow")

    run3.finish()
    previous = wandb.init(mode="offline", reinit=return_previous)

    # run2 is returned because it is the most recent unfinished run.
    assert previous is run2
