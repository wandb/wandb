"""
start method tests.
"""

import platform

import pytest
from wandb.errors import UsageError


def test_default(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init()
        run_id = run.id
        run.log(dict(val=1))
        run.finish()

    summary = relay.context.get_run_summary(run_id)
    telemetry = relay.context.get_run_telemetry(run_id)
    assert summary["val"] == 1
    assert telemetry and 5 in telemetry.get("8", [])


def test_junk(relay_server, wandb_init):
    with relay_server():
        with pytest.raises(UsageError):
            run = wandb_init(settings=dict(start_method="junk"))
            run.finish()


def test_spawn(relay_server, wandb_init):
    # note: passing in dict to settings (here and below)
    # since this will set start_method with source=Source.INIT
    with relay_server() as relay:
        run = wandb_init(settings=dict(start_method="spawn"))
        run_id = run.id
        run.log(dict(val=1))
        run.finish()

    telemetry = relay.context.get_run_telemetry(run_id)
    assert telemetry and 5 in telemetry.get("8", [])


@pytest.mark.skipif(platform.system() == "Windows", reason="win has no fork")
def test_fork(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init(settings=dict(start_method="fork"))
        run_id = run.id
        run.log(dict(val=1))
        run.finish()

    telemetry = relay.context.get_run_telemetry(run_id)
    assert telemetry and 6 in telemetry.get("8", [])


@pytest.mark.skipif(platform.system() == "Windows", reason="win has no forkserver")
def test_forkserver(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init(settings=dict(start_method="forkserver"))
        run_id = run.id
        run.log(dict(val=1))
        run.finish()

    telemetry = relay.context.get_run_telemetry(run_id)
    assert telemetry and 7 in telemetry.get("8", [])


def test_thread(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init(settings=dict(start_method="thread"))
        run_id = run.id
        run.log(dict(val=1))
        run.finish()

    telemetry = relay.context.get_run_telemetry(run_id)
    assert telemetry and 8 in telemetry.get("8", [])
