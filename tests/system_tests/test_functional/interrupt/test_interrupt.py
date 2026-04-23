import pathlib
import subprocess
import threading

import pytest
import wandb

from tests.fixtures.wandb_backend_spy import WandbBackendSpy


def test_run_stop_interrupts(wandb_backend_spy: WandbBackendSpy):
    wandb_backend_spy.stub_filestream(
        {"stopped": True},
        status=200,
    )

    script = pathlib.Path(__file__).parent / "pass_if_interrupted.py"
    subprocess.check_call(["python", str(script)])


def test_uses_stop_fn(
    monkeypatch: pytest.MonkeyPatch,
    wandb_backend_spy: WandbBackendSpy,
):
    monkeypatch.setattr("wandb.sdk.wandb_run._STOP_POLLING_INTERVAL", 0.1)
    stopped = threading.Event()
    wandb_backend_spy.stub_filestream(
        {"stopped": True},
        status=200,
    )

    with wandb.init(settings=wandb.Settings(stop_fn=stopped.set)):
        assert stopped.wait(timeout=30)
