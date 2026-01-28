from __future__ import annotations

import pathlib
import tempfile
from typing import Any

import pytest
import wandb
from wandb.apis.public import DownloadHistoryResult, Run


def stub_run_parquet_history(
    wandb_backend_spy,
    parquet_file_server,
    parquet_files_locations: list[str],
    live_data: list[dict[str, Any]] | None = None,
):
    gql = wandb_backend_spy.gql
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="RunParquetHistory"),
        gql.once(
            content={
                "data": {
                    "project": {
                        "run": {
                            "parquetHistory": {
                                "parquetUrls": [
                                    f"http://localhost:{parquet_file_server.port}/{path}"
                                    for path in parquet_files_locations
                                ],
                                **(
                                    {"liveData": live_data}
                                    if live_data is not None
                                    else {}
                                ),
                            }
                        }
                    }
                }
            }
        ),
    )


def stub_api_run_history_keys(wandb_backend_spy, last_step: int):
    gql = wandb_backend_spy.gql
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="RunHistoryKeys"),
        gql.Constant(
            content={
                "data": {
                    "project": {
                        "run": {
                            "historyKeys": {
                                "lastStep": last_step,
                            }
                        }
                    }
                }
            }
        ),
    )


def test_run_beta_scan_history(wandb_backend_spy, parquet_file_server):
    # Create in-memory parquet file with run data
    # and serve it over HTTP.
    parquet_data_path = "parquet/1.parquet"
    run_data = {
        "_step": [0, 1, 2],
        "acc": [0.5, 0.75, 0.9],
        "loss": [1.0, 0.5, 0.1],
    }
    parquet_file_server.serve_data_as_parquet_file(parquet_data_path, run_data)
    stub_run_parquet_history(
        wandb_backend_spy, parquet_file_server, [parquet_data_path]
    )
    stub_api_run_history_keys(wandb_backend_spy, 2)
    with wandb.init() as run:
        pass
    run = wandb.Api().run(
        f"{run.entity}/{run.project}/{run.id}",
    )

    scan = run.beta_scan_history()

    history = [row for row in scan]
    assert history == [
        {"_step": 0, "acc": 0.5, "loss": 1.0},
        {"_step": 1, "acc": 0.75, "loss": 0.5},
        {"_step": 2, "acc": 0.9, "loss": 0.1},
    ]


def test_run_beta_scan_history__iter_resets(
    wandb_backend_spy,
    parquet_file_server,
):
    # Create sample parquet data with history metrics
    parquet_data_path = "parquet/1.parquet"
    run_data = {
        "_step": [0, 1, 2],
        "acc": [0.5, 0.75, 0.9],
        "loss": [1.0, 0.5, 0.1],
    }
    parquet_file_server.serve_data_as_parquet_file(parquet_data_path, run_data)
    stub_run_parquet_history(
        wandb_backend_spy, parquet_file_server, [parquet_data_path]
    )
    stub_api_run_history_keys(wandb_backend_spy, 2)
    with wandb.init() as run:
        pass
    run = wandb.Api().run(
        f"{run.entity}/{run.project}/{run.id}",
    )

    scan = run.beta_scan_history()

    history = []
    i = 0
    for row in scan:
        if i >= 2:
            break
        history.append(row)
        i += 1
    assert len(history) == 2
    assert history == [
        {"_step": 0, "acc": 0.5, "loss": 1.0},
        {"_step": 1, "acc": 0.75, "loss": 0.5},
    ]

    history = []
    for row in scan:
        history.append(row)

    assert len(history) == 3
    assert history == [
        {"_step": 0, "acc": 0.5, "loss": 1.0},
        {"_step": 1, "acc": 0.75, "loss": 0.5},
        {"_step": 2, "acc": 0.9, "loss": 0.1},
    ]


def test_run_beta_scan_history__exits_on_run_max_step(
    wandb_backend_spy,
    parquet_file_server,
):
    # Create sample parquet data with history metrics
    parquet_data_path = "parquet/1.parquet"
    run_data = {
        "_step": [0, 1, 2],
        "acc": [0.5, 0.75, 0.9],
        "loss": [1.0, 0.5, 0.1],
    }
    parquet_file_server.serve_data_as_parquet_file(parquet_data_path, run_data)
    stub_run_parquet_history(
        wandb_backend_spy, parquet_file_server, [parquet_data_path]
    )
    stub_api_run_history_keys(wandb_backend_spy, 2)
    with wandb.init() as run:
        pass
    run = wandb.Api().run(
        f"{run.entity}/{run.project}/{run.id}",
    )

    scan = run.beta_scan_history(max_step=100)

    history = [row for row in scan]
    assert history == [
        {"_step": 0, "acc": 0.5, "loss": 1.0},
        {"_step": 1, "acc": 0.75, "loss": 0.5},
        {"_step": 2, "acc": 0.9, "loss": 0.1},
    ]


def test_run_beta_scan_history__exits_on_requested_max_step(
    wandb_backend_spy,
    parquet_file_server,
):
    # Create sample parquet data with history metrics
    parquet_data_path = "parquet/1.parquet"
    run_data = {
        "_step": [0, 1, 2],
        "acc": [0.5, 0.75, 0.9],
        "loss": [1.0, 0.5, 0.1],
    }
    parquet_file_server.serve_data_as_parquet_file(parquet_data_path, run_data)
    stub_run_parquet_history(
        wandb_backend_spy, parquet_file_server, [parquet_data_path]
    )
    stub_api_run_history_keys(wandb_backend_spy, 2)
    with wandb.init() as run:
        pass

    run = wandb.Api().run(
        f"{run.entity}/{run.project}/{run.id}",
    )

    scan = run.beta_scan_history(max_step=1)

    history = [row for row in scan]
    assert history == [
        {"_step": 0, "acc": 0.5, "loss": 1.0},
    ]


@pytest.mark.parametrize(
    "parquet_files,live_data",
    [
        (["parquet/1.parquet", "parquet/2.parquet"], None),
        (["parquet/1.parquet", "parquet/2.parquet"], [{"_step": 3}]),
    ],
    ids=["no_live_data", "contains_live_data"],
)
def test_run_download_history_exports(
    wandb_backend_spy,
    parquet_file_server,
    parquet_files,
    live_data,
):
    """Test downloading history exports with different configurations."""
    # Create sample parquet data with history metrics
    run_data = {"_step": [0, 1, 2]}
    for parquet_path in parquet_files:
        parquet_file_server.serve_data_as_parquet_file(parquet_path, run_data)
    stub_run_parquet_history(
        wandb_backend_spy,
        parquet_file_server,
        parquet_files,
        live_data=live_data,
    )
    stub_api_run_history_keys(wandb_backend_spy, 2)
    with wandb.init() as run:
        pass

    api_run: Run = wandb.Api().run(
        f"{run.entity}/{run.project}/{run.id}",
    )

    download_dir = tempfile.mkdtemp()
    download_result: DownloadHistoryResult = api_run.download_history_exports(
        download_dir=download_dir,
        require_complete_history=False,
    )

    expected_file_names = [
        pathlib.Path(
            download_dir,
            f"{run.entity}_{run.project}_{run.id}_{i}.runhistory.parquet",
        )
        for i in range(len(parquet_files))
    ]
    assert download_result.paths == expected_file_names

    for path in download_result.paths:
        assert path.exists()

    assert download_result.contains_live_data == (
        live_data is not None and len(live_data) > 0
    )
