import pathlib
import subprocess

from tests.fixtures.wandb_backend_spy import WandbBackendSpy


def test_run_stops_if_asked(wandb_backend_spy: WandbBackendSpy):
    wandb_backend_spy.stub_filestream(
        {"stopped": True},
        status=200,
    )

    script = pathlib.Path(__file__).parent / "pass_if_interrupted.py"
    subprocess.check_call(["python", str(script)])
