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

    runs = list(wandb.Api().runs(f"{user}/{project}"))
    assert len(runs) == exps * runs_per_exp
    for run in runs:
        # https://stackoverflow.com/a/50645935
        assert len(list(run.scan_history())) == steps
