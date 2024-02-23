import sys

import pytest
import wandb
from wandb.apis.importers.internals.util import Namespace
from wandb.apis.importers.mlflow import MlflowImporter


@pytest.mark.timeout(60)
@pytest.mark.skipif(sys.version_info < (3, 8), reason="MLFlow requires python>=3.8")
def test_mlflow(request, prelogged_mlflow_server, mlflow_logging_config, user):
    # TODO: This test is tightly coupled with the `prelogged_mlflow_server` fixture; refactor

    project = "imported-from-mlflow"

    importer = MlflowImporter(
        dst_base_url=request.config.wandb_server_settings.base_url,
        dst_api_key=user,
        mlflow_tracking_uri=prelogged_mlflow_server.base_url,
    )
    runs = importer.collect_runs()
    importer.import_runs(runs, namespace=Namespace(user, project))

    api = wandb.Api()
    runs = list(api.runs(f"{user}/{project}"))
    assert len(runs) == mlflow_logging_config.total_runs
    for run in runs:
        # Check history
        history = list(run.scan_history())
        assert len(history) == mlflow_logging_config.n_steps_per_run
        for r in history:
            assert len(r) == 4  # 1 step + 3 (int, float, bool) metrics

        # Check params
        assert len(run.config) == 10  # 9 keys + `imported_mlflow_tags`

        # Check artifacts (note: all mlflow artifacts are lumped
        # into a single wandb.Artifact, so len(art) == 1 always)
        art = list(run.logged_artifacts())[0]
        assert len(art.files()) == mlflow_logging_config.total_files
