"""start method tests."""

import platform

import pytest
import wandb
from wandb.errors import UsageError


def test_default(wandb_backend_spy):
    run = wandb.init()
    run_id = run.id
    run.log(dict(val=1))
    run.finish()

    with wandb_backend_spy.freeze() as snapshot:
        summary = snapshot.summary(run_id=run_id)
        telemetry = snapshot.telemetry(run_id=run_id)
        assert summary["val"] == 1
        assert telemetry and 5 in telemetry.get("8", [])


def test_junk():
    with pytest.raises(UsageError):
        run = wandb.init(settings=dict(start_method="junk"))
        run.finish()


def test_spawn(wandb_backend_spy):
    # note: passing in dict to settings (here and below)
    # since this will set start_method with source=Source.INIT
    run = wandb.init(settings=dict(start_method="spawn"))
    run_id = run.id
    run.log(dict(val=1))
    run.finish()

    with wandb_backend_spy.freeze() as snapshot:
        telemetry = snapshot.telemetry(run_id=run_id)
        assert telemetry and 5 in telemetry.get("8", [])


@pytest.mark.skipif(platform.system() == "Windows", reason="win has no fork")
def test_fork(wandb_backend_spy):
    run = wandb.init(settings=dict(start_method="fork"))
    run_id = run.id
    run.log(dict(val=1))
    run.finish()

    with wandb_backend_spy.freeze() as snapshot:
        telemetry = snapshot.telemetry(run_id=run_id)
        assert telemetry and 6 in telemetry.get("8", [])


@pytest.mark.skipif(platform.system() == "Windows", reason="win has no forkserver")
def test_forkserver(wandb_backend_spy):
    run = wandb.init(settings=dict(start_method="forkserver"))
    run_id = run.id
    run.log(dict(val=1))
    run.finish()

    with wandb_backend_spy.freeze() as snapshot:
        telemetry = snapshot.telemetry(run_id=run_id)
        assert telemetry and 7 in telemetry.get("8", [])


def test_thread(wandb_backend_spy):
    run = wandb.init(settings=dict(start_method="thread"))
    run_id = run.id
    run.log(dict(val=1))
    run.finish()

    with wandb_backend_spy.freeze() as snapshot:
        telemetry = snapshot.telemetry(run_id=run_id)
        assert telemetry and 8 in telemetry.get("8", [])
