import pandas as pd
import pytest
import wandb
from wandb.apis.importers import WandbParquetImporter


@pytest.mark.timeout(300)
def test_wandb_runs(
    prelogged_wandb_server,
    other_wandb_server,
    settings,
    settings2,
    wandb_logging_config,
):
    alt_user = prelogged_wandb_server
    user = other_wandb_server
    source_base_url = f"http://localhost:{settings.local_base_port}"
    dest_base_url = f"http://localhost:{settings2.local_base_port}"

    project = "test"
    overrides = {"entity": user, "project": project}
    importer = WandbParquetImporter(
        source_base_url=source_base_url,
        source_api_key=alt_user,
        dest_base_url=dest_base_url,
        dest_api_key=user,
    )
    importer.import_all_runs(alt_user, overrides=overrides)

    #

    api = wandb.Api(api_key=user, overrides={"base_url": dest_base_url})
    runs = api.runs(f"{user}/test")
    runs = list(runs)

    assert len(runs) == wandb_logging_config.n_experiments
    for run in runs:
        history = run.scan_history()
        df = pd.DataFrame(history)
        # print(f"{df.columns=}")
        metric_cols = df.columns.str.startswith("metric")
        media_cols = ["df", "img", "audio", "pc", "html", "plotly_fig", "mol"]

        metric_df = df.loc[:, metric_cols].dropna(how="all")
        media_df = df.loc[:, media_cols].dropna(how="all")

        assert metric_df.shape == (
            wandb_logging_config.n_steps,
            wandb_logging_config.n_metrics,
        )
        assert media_df.shape == (1, 7)
