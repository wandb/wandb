import pytest

import wandb
from wandb.apis.importers import MlflowImporter


@pytest.mark.timeout(300)
def test_mlflow(prelogged_mlflow_server, user):
    mlflow_server, exps, runs_per_exp, steps = prelogged_mlflow_server

    project = "mlflow-import-testing"
    overrides = {
        "entity": user,
        "project": project,
    }
    importer = MlflowImporter(mlflow_tracking_uri=mlflow_server)
    importer.send_everything_parallel(overrides=overrides)

    api = wandb.Api()
    # this assumes knowledge of the prelogged_mlflow_server
    # we could move "logging data to mlflow" out of the fixture and into this test

    runs = list(api.runs(f"{user}/{project}"))
    assert len(runs) == exps * runs_per_exp

    for run in runs:
        i = 0
        for i, _ in enumerate(run.scan_history(), start=1):
            pass

        length = i
        assert length == steps
