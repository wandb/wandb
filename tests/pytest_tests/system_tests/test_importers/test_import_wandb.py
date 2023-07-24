import pandas as pd
import pytest
import wandb
from wandb.apis.importers import WandbParquetImporter


@pytest.mark.timeout(300)
def test_wandb_runs(wandb_server_src, wandb_server_dst, wandb_logging_config):
    # Import
    importer = WandbParquetImporter(
        src_base_url=wandb_server_src.server.base_url,
        src_api_key=wandb_server_src.user,
        dst_base_url=wandb_server_dst.server.base_url,
        dst_api_key=wandb_server_dst.user,
    )

    importer.import_all_runs(
        entity=wandb_server_src.user,
        config={
            "entity": wandb_server_dst.user,
            "project": wandb_logging_config.project_name,
        },
    )

    # Check if import was successful
    api = wandb.Api(
        api_key=wandb_server_dst.user,
        overrides={"base_url": wandb_server_dst.server.base_url},
    )
    entity = wandb_server_dst.user
    project = wandb_logging_config.project_name

    runs = api.runs(f"{entity}/{project}")
    runs = list(runs)

    assert len(runs) == wandb_logging_config.n_experiments
    for run in runs:
        history = run.scan_history()
        df = pd.DataFrame(history)
        metric_cols = df.columns.str.startswith("metric")
        media_cols = ["df", "img", "audio", "pc", "html", "plotly_fig", "mol"]

        metric_df = df.loc[:, metric_cols].dropna(how="all")
        media_df = df.loc[:, media_cols].dropna(how="all")

        assert metric_df.shape == (
            wandb_logging_config.n_steps,
            wandb_logging_config.n_metrics,
        )
        assert media_df.shape == (1, 7)


@pytest.mark.timeout(300)
def test_wandb_reports(wandb_server_src, wandb_server_dst, wandb_logging_config):
    # Import
    importer = WandbParquetImporter(
        src_base_url=wandb_server_src.server.base_url,
        src_api_key=wandb_server_src.user,
        dst_base_url=wandb_server_dst.server.base_url,
        dst_api_key=wandb_server_dst.user,
    )

    importer.import_all_reports(
        entity=wandb_server_src.user,
        config={
            "entity": wandb_server_dst.user,
            "project": wandb_logging_config.project_name,
        },
    )

    # Check if import was successful
    api = wandb.Api(
        api_key=wandb_server_dst.user,
        overrides={"base_url": wandb_server_dst.server.base_url},
    )
    entity = wandb_server_dst.user
    project = wandb_logging_config.project_name

    reports = api.reports(f"{entity}/{project}")
    reports = list(reports)

    assert len(reports) == wandb_logging_config.n_reports
