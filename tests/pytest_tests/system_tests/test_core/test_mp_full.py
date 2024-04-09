"""multiproc full tests."""

import importlib
import sys
import time

import pytest
import wandb
from wandb.errors import UsageError


def train(run, add_val):
    time.sleep(1)
    run.log(dict(mystep=1, val=2 + add_val))
    run.log(dict(mystep=2, val=8 + add_val))
    run.log(dict(mystep=3, val=3 + add_val))
    run.log(dict(val2=4 + add_val))
    run.log(dict(val2=1 + add_val))
    time.sleep(1)


def test_multiproc_default(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init()
        train(run, 0)
        run.finish()

    summary = relay.context.get_run_summary(run.id)
    assert summary["val"] == 3
    assert summary["val2"] == 1
    assert summary["mystep"] == 3


@pytest.mark.timeout(300)
def test_multiproc_spawn(runner, user):
    # WB5640. Before the WB5640 fix this code fragment would raise an
    # exception, this test checks that it runs without error
    with runner.isolated_filesystem():
        from tests.pytest_tests.assets import test_mod

        test_mod.main()
        sys.modules["__main__"].__spec__ = importlib.machinery.ModuleSpec(
            name="tests.pytest_tests.assets.test_mod",
            loader=importlib.machinery.BuiltinImporter,
        )
        test_mod.main()
        sys.modules["__main__"].__spec__ = None
        # run this to get credit for the diff
        test_mod.mp_func()


def test_missing_attach_id(wandb_init):
    run = wandb_init()
    with pytest.raises(UsageError):
        wandb._attach(attach_id=None, run_id=None)
    run.finish()
