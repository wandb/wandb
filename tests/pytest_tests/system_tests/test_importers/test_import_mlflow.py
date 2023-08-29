import sys

import pytest
import wandb
from wandb.apis.importers import ImportConfig, MlflowImporter


@pytest.mark.timeout(60)
@pytest.mark.skipif(sys.version_info < (3, 8), reason="MLFlow requires python>=3.8")
def test_mlflow(new_prelogged_mlflow_server, mlflow_logging_config, user):
    project = "mlflow-import-testing"
    importer = MlflowImporter(mlflow_tracking_uri=new_prelogged_mlflow_server.base_url)

    config = ImportConfig(entity=user, project=project)
    runs = importer.collect_runs()
    importer.import_runs(runs, config)

    runs = list(wandb.Api().runs(f"{user}/{project}"))
    assert len(runs) == mlflow_logging_config.total_runs
    for run in runs:
        # https://stackoverflow.com/a/50645935
        assert len(list(run.scan_history())) == mlflow_logging_config.n_steps_per_run

        # only one artifact containing everything in mlflow
        art = list(run.logged_artifacts())[0]
        assert len(art.files()) == mlflow_logging_config.total_files
