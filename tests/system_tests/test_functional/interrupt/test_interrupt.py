import os
import pathlib
import subprocess


def test_run_stops_if_asked(wandb_backend_spy):
    gql = wandb_backend_spy.gql
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="RunStoppedStatus"),
        gql.Constant(content={"data": {"project": {"run": {"stopped": True}}}}),
    )

    script = pathlib.Path(__file__).parent / "pass_if_interrupted.py"
    subprocess.check_call(
        ["python", str(script)],
        env={
            "COVERAGE_PROCESS_START": "1",
            **os.environ,
        },
    )
