from types import SimpleNamespace
from typing import Any

import wandb
from wandb.sdk.interface.interface_queue import InterfaceQueue


def test_make_run_records_offline_resume_mode():
    interface = InterfaceQueue()
    settings = wandb.Settings(
        mode="offline",
        resume="must",
        run_id="run-id",
    )
    run: Any = SimpleNamespace(
        _settings=settings,
        _start_time=None,
        _starting_step=None,
        _forked=False,
        _config=None,
        _telemetry_obj=None,
        _start_runtime=None,
    )

    record = interface._make_run(run)

    assert record.resume_mode == "must"


def test_make_run_omits_online_resume_mode():
    interface = InterfaceQueue()
    settings = wandb.Settings(
        mode="online",
        resume="allow",
        run_id="run-id",
    )
    run: Any = SimpleNamespace(
        _settings=settings,
        _start_time=None,
        _starting_step=None,
        _forked=False,
        _config=None,
        _telemetry_obj=None,
        _start_runtime=None,
    )

    record = interface._make_run(run)

    assert record.resume_mode == ""
