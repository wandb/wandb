import pytest
import wandb
from wandb.apis.importers import WandbParquetImporter
import pandas as pd


@pytest.mark.timeout(30)
def test_wandb_runs(
    prelogged_wandb_server,
    wandb_logging_config,
    alt_user,
    user,
    base_url_alt,
    base_url,
):
    n_steps = wandb_logging_config["n_steps"]
    n_metrics = wandb_logging_config["n_metrics"]
    n_experiments = wandb_logging_config["n_experiments"]

    project = "test"
    overrides = {"entity": user, "project": project}
    importer = WandbParquetImporter(
        source_base_url=base_url_alt,
        source_api_key=alt_user,
        dest_base_url=base_url,
        dest_api_key=user,
    )
    importer.import_all_runs(alt_user, overrides=overrides)

    #

    api = wandb.Api(api_key=user, overrides={"base_url": base_url})
    runs = api.runs(f"{user}/test")
    runs = list(runs)

    assert len(runs) == n_experiments
    for run in runs:
        history = run.scan_history()
        df = pd.DataFrame(history)
        # print(f"{df.columns=}")
        metric_cols = df.columns.str.startswith("metric")
        media_cols = ["df", "img", "audio", "pc", "html", "plotly_fig", "mol"]

        metric_df = df.loc[:, metric_cols].dropna(how="all")
        media_df = df.loc[:, media_cols].dropna(how="all")

        assert metric_df.shape == (n_steps, n_metrics)
        assert media_df.shape == (1, 7)
