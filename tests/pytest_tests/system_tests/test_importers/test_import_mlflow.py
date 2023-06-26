import sys

import pytest
import wandb
from wandb.apis.importers import MlflowImporter


@pytest.mark.timeout(60)
@pytest.mark.skipif(sys.version_info < (3, 8), reason="MLFlow requires python>=3.8")
def test_mlflow(new_prelogged_mlflow_server, mlflow_logging_config, user):
    project = "mlflow-import-testing"
    overrides = {
        "entity": user,
        "project": project,
    }
    importer = MlflowImporter(mlflow_tracking_uri=new_prelogged_mlflow_server.base_url)
    importer.import_all_runs(overrides=overrides)

    runs = list(wandb.Api().runs(f"{user}/{project}"))
    assert len(runs) == mlflow_logging_config.total_runs
    for run in runs:
        # https://stackoverflow.com/a/50645935
        assert len(list(run.scan_history())) == mlflow_logging_config.n_steps_per_run

        # only one artifact containing everything in mlflow
        art = list(run.logged_artifacts())[0]
        assert len(art.files()) == mlflow_logging_config.total_files
