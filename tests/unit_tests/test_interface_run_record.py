from types import SimpleNamespace
from typing import Any

import pytest
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

    assert record.resume_mode is True


def test_make_run_records_online_resume_mode():
    interface = InterfaceQueue()
    settings = wandb.Settings(
        mode="online",
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

    assert record.resume_mode is True


@pytest.mark.parametrize(
    ("resume", "expected"),
    [
        ("allow", True),
        ("must", True),
        ("auto", True),
        ("never", False),
        (None, False),
    ],
)
def test_make_run_record_resume_mode_mapping(resume, expected):
    interface = InterfaceQueue()
    settings = wandb.Settings(mode="online", resume=resume, run_id="run-id")
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

    assert record.resume_mode is expected
