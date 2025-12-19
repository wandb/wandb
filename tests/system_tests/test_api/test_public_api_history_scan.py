from __future__ import annotations

import wandb


def stub_run_parquet_history(
    wandb_backend_spy,
    parquet_file_server,
    parquet_files_locations: list[str],
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
                                ]
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


def test_sweep_run_history_scan(
    wandb_backend_spy,
    parquet_file_server,
    user,
):
    sweep_config = {
        "name": "test-sweep",
        "method": "random",
        "parameters": {
            "learning_rate": {"min": 0.001, "max": 0.1},
        },
    }
    sweep_id = wandb.sweep(sweep_config, project="test")
    parquet_data_path = "parquet/sweep_run.parquet"
    run_data = {
        "_step": [0],
        "acc": [0.5],
    }
    parquet_file_server.serve_data_as_parquet_file(parquet_data_path, run_data)
    stub_run_parquet_history(
        wandb_backend_spy, parquet_file_server, [parquet_data_path]
    )
    stub_api_run_history_keys(wandb_backend_spy, 2)
    with wandb.init(settings={"sweep_id": sweep_id}):
        pass

    api = wandb.Api()
    sweep = api.sweep(f"{user}/test/sweeps/{sweep_id}")

    sweep_runs = list(sweep.runs)
    assert len(sweep_runs) == 1

    sweep_run = sweep_runs[0]
    scan = sweep_run.beta_scan_history()
    history = [row for row in scan]
    assert history == [{"_step": 0, "acc": 0.5}]
