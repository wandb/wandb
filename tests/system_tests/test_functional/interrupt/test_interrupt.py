import pathlib
import subprocess
import threading

import pytest
import wandb

from tests.fixtures.wandb_backend_spy import WandbBackendSpy


@pytest.fixture(autouse=True)
def fast_stop_polling_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("wandb.sdk.wandb_run._STOP_POLLING_INTERVAL", 0.1)


def test_run_stop_interrupts(wandb_backend_spy: WandbBackendSpy):
    wandb_backend_spy.stub_filestream(
        {"stopped": True},
        status=200,
    )

    script = pathlib.Path(__file__).parent / "pass_if_interrupted.py"
    subprocess.check_call(["python", str(script)])


def test_uses_stop_fn(wandb_backend_spy: WandbBackendSpy):
    stopped = threading.Event()
    wandb_backend_spy.stub_filestream(
        {"stopped": True},
        status=200,
    )

    with wandb.init(settings=wandb.Settings(stop_fn=stopped.set)):
        assert stopped.wait(timeout=30)


def test_stop_on_fatal_error(wandb_backend_spy: WandbBackendSpy):
    stopped = threading.Event()
    wandb_backend_spy.stub_filestream(
        "non retryable status code",
        status=400,
    )

    with wandb.init(
        settings=wandb.Settings(
            stop_fn=stopped.set,
            stop_on_fatal_error=True,
        )
    ):
        assert stopped.wait(timeout=30)
