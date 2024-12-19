import pathlib
import subprocess
from typing import Any


def _run_stopped_response(stopped: bool) -> dict[str, Any]:
    return {"data": {"project": {"run": {"stopped": stopped}}}}


def test_run_stops_if_asked(wandb_backend_spy):
    gql = wandb_backend_spy.gql
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="RunStoppedStatus"),
        gql.Sequence(
            [
                # Respond False to the first check so that the True response
                # is more likely to be observed during time.sleep().
                gql.Constant(content=_run_stopped_response(False)),
                gql.Constant(content=_run_stopped_response(True)),
            ]
        ),
    )

    script = pathlib.Path(__file__).parent / "pass_if_interrupted.py"
    subprocess.check_call(["python", str(script)])
