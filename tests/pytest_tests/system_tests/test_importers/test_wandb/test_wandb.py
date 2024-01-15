import unittest

import pytest
import wandb
from wandb.apis.importers.internals.config import Namespace
from wandb.apis.importers.wandb import WandbImporter


@pytest.fixture
def importer(wandb_server_src, wandb_server_dst):
    with unittest.mock.patch("wandb.sdk.lib.apikey.write_key"):
        importer = WandbImporter(
            src_base_url=wandb_server_src.server.base_url,
            src_api_key=wandb_server_src.user,
            dst_base_url=wandb_server_dst.server.base_url,
            dst_api_key=wandb_server_dst.user,
        )
        yield importer


@pytest.mark.timeout(300)
def test_import_reports(wandb_server_src, wandb_server_dst, wandb_logging_config):
    src_entity, src_project = wandb_server_src.user, "test"
    dst_entity, dst_project = wandb_server_dst.user, "test"

    # Initially, src has something and dst has nothing
    src_api = wandb.Api(
        api_key=wandb_server_src.user,
        overrides={"base_url": wandb_server_src.server.base_url},
    )
    dst_api = wandb.Api(
        api_key=wandb_server_dst.user,
        overrides={"base_url": wandb_server_dst.server.base_url},
    )

    src_reports = [p for p in src_api.reports(f"{src_entity}/{src_project}")]
    # dst_reports = [p for p in dst_api.reports(f"{dst_entity}/{dst_project}")]

    assert len(src_reports) == 1
    # assert len(dst_reports) == 0

    importer = WandbImporter(
        src_base_url=wandb_server_src.server.base_url,
        src_api_key=wandb_server_src.user,
        dst_base_url=wandb_server_dst.server.base_url,
        dst_api_key=wandb_server_dst.user,
    )

    importer.import_reports()

    # Initially, src has something and dst has nothing
    src_api = wandb.Api(
        api_key=wandb_server_src.user,
        overrides={"base_url": wandb_server_src.server.base_url},
    )
    dst_api = wandb.Api(
        api_key=wandb_server_dst.user,
        overrides={"base_url": wandb_server_dst.server.base_url},
    )

    src_reports = [p for p in src_api.reports(f"{src_entity}/{src_project}")]
    dst_reports = [p for p in dst_api.reports(f"{dst_entity}/{dst_project}")]

    assert len(src_reports) == 1
    assert len(dst_reports) == 1


@pytest.mark.timeout(300)
def test_import_runs(wandb_server_src, wandb_server_dst, wandb_logging_config):
    src_entity, src_project = wandb_server_src.user, "test"
    dst_entity, dst_project = wandb_server_dst.user, "test"

    # Initially, src has something and dst has nothing
    src_api = wandb.Api(
        api_key=wandb_server_src.user,
        overrides={"base_url": wandb_server_src.server.base_url},
    )
    dst_api = wandb.Api(
        api_key=wandb_server_dst.user,
        overrides={"base_url": wandb_server_dst.server.base_url},
    )

    src_projects = [p for p in src_api.projects(src_entity)]
    dst_projects = [p for p in dst_api.projects(dst_entity)]

    assert len(src_projects) == 1
    assert len(dst_projects) == 0

    # Then import
    importer = WandbImporter(
        src_base_url=wandb_server_src.server.base_url,
        src_api_key=wandb_server_src.user,
        dst_base_url=wandb_server_dst.server.base_url,
        dst_api_key=wandb_server_dst.user,
    )

    importer.import_runs(
        # namespaces=[Namespace("wandb_server_src", "test")],
        # use remap because the src_entity won't exist yet on the dst server.
        # in future, also test the src->src case.
        namespace_remapping={
            Namespace(src_entity, src_project): Namespace(dst_entity, dst_project)
        },
    )

    # Now dst has the same thing as src
    src_api = wandb.Api(
        api_key=wandb_server_src.user,
        overrides={"base_url": wandb_server_src.server.base_url},
    )
    dst_api = wandb.Api(
        api_key=wandb_server_dst.user,
        overrides={"base_url": wandb_server_dst.server.base_url},
    )

    src_projects = [p for p in src_api.projects(src_entity)]
    dst_projects = [p for p in dst_api.projects(dst_entity)]

    assert len(src_projects) == 1
    assert len(dst_projects) == 1

    src_runs = list(src_api.runs(f"{src_entity}/{src_project}"))
    dst_runs = list(dst_api.runs(f"{dst_entity}/{dst_project}"))

    assert len(src_runs) == len(dst_runs)
    for src_run, dst_run in zip(src_runs, dst_runs):
        src_history = list(src_run.scan_history())
        dst_history = list(dst_run.scan_history())

        assert len(src_history) == len(dst_history)
        for src_row, dst_row in zip(src_history, dst_history):
            assert src_row == dst_row


# runs = api.runs(f"{wandb_server_src.user}/{wandb_logging_conf```ig.project_name}")
# runs = list(runs)
# assert len(runs) == 1

# for run in runs:
#     history = run.scan_history()
#     df = pd.DataFrame(history)
#     metric_cols = df.columns.str.startswith("metric")
#     media_cols = ["df", "img", "audio", "pc", "html", "plotly_fig", "mol"]

#     metric_df = df.loc[:, metric_cols].dropna(how="all")
#     media_df = df.loc[:, media_cols].dropna(how="all")

#     assert metric_df.shape == (
#         wandb_logging_config.n_steps,
#         wandb_logging_config.n_metrics,
#     )
#     assert media_df.shape == (1, len(media_cols))
