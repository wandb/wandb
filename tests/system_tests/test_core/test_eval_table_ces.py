"""End-to-end tests for CES-backed EvalTables through wandb-core.

These log EvalTables against the local W&B server, with the backend spy's
fake CES in place of the CoreWeave Evaluation Service.
"""

from __future__ import annotations

import os

import pytest
import wandb
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.data_types.eval_table import _writer_ces

_ROWS = [
    {
        "input": {"question": "2+2"},
        "output": {"answer": "4"},
        "scores": {"correct": True, "confidence": 0.9},
    },
    {
        "input": {"question": "3+3"},
        "output": {"answer": "5"},
        "scores": {"correct": False, "confidence": 0.25},
    },
]


@pytest.fixture(autouse=True)
def fake_ces(wandb_backend_spy, wandb_backend_proxy_server, monkeypatch) -> None:
    """Point wandb at the spy's fake CES, and enable EVAL_TABLES_CES."""
    monkeypatch.setenv("WANDB_CES_BASE_URL", wandb_backend_proxy_server.ces_base_url)

    features = [{"name": pb.ServerFeature.Name(pb.EVAL_TABLES_CES), "isEnabled": True}]
    gql = wandb_backend_spy.gql
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="ServerFeaturesQuery"),
        gql.Constant(content={"data": {"serverInfo": {"features": features}}}),
    )


def _log_eval_table() -> wandb.Run:
    with wandb.init() as run:
        run.log(
            {
                "eval": wandb.EvalTable(
                    columns=["question", "answer", "correct", "confidence"],
                    data=[
                        ["2+2", "4", True, 0.9],
                        ["3+3", "5", False, 0.25],
                    ],
                    input_columns=["question"],
                    output_columns=["answer"],
                    score_columns=["correct", "confidence"],
                    backend="ces",
                )
            }
        )
    return run


def _project_internal_id(run: wandb.Run) -> str:
    response = wandb.Api()._service_api.execute_graphql(
        """
        query ProjectInternalID($entityName: String!, $projectName: String!) {
            project(entityName: $entityName, name: $projectName) {
                internalId
            }
        }
        """,
        {"entityName": run.entity, "projectName": run.project},
    )
    return response["project"]["internalId"]


def _assert_logged_to_ces(wandb_backend_spy, run: wandb.Run) -> None:
    """Assert CES received the table, and the run's history has its marker."""
    with wandb_backend_spy.freeze() as snapshot:
        requests = snapshot.ces_requests()
        history = snapshot.history(run_id=run.id)

    tables_path = (
        "/evaluations/v1/namespaces/wandb/scopes/"
        f"{_project_internal_id(run)}/eval-tables"
    )
    assert [(r.method, r.path) for r in requests] == [
        ("POST", tables_path),
        ("POST", f"{tables_path}/eval-id/columns"),
        ("POST", f"{tables_path}/eval-id/rows"),
        ("POST", f"{tables_path}/eval-id/versions"),
    ]

    create, columns, rows, _ = requests
    assert create.body == {"name": "eval"}
    assert columns.body == {
        "dataset_fields": [
            {"source": "input", "name": "question", "value_type": "string"},
            {"source": "output", "name": "answer", "value_type": "string"},
        ],
        "scorers": [
            {"name": "correct", "value_type": "boolean"},
            {"name": "confidence", "value_type": "number"},
        ],
    }
    assert rows.body == {"rows": _ROWS}

    prefix = requests[0].idempotency_key.removesuffix("-create")
    assert [r.idempotency_key for r in requests] == [
        f"{prefix}-create",
        f"{prefix}-columns",
        f"{prefix}-rows-0",
        f"{prefix}-version",
    ]

    assert history[0]["eval"] == {
        "_type": "eval-table-ces",
        "schema_version": 1,
        "ncols": 4,
        "nrows": 2,
        "log_mode": "IMMUTABLE",
        "evaluation_id": "eval-id",
        "evaluation_version_id": "eval-version-id",
        "dataset_id": "dataset-id",
        "dataset_version_id": "dataset-version-id",
    }


def test_logs_ces_eval_table(wandb_backend_spy):
    run = _log_eval_table()

    _assert_logged_to_ces(wandb_backend_spy, run)


def test_logs_ces_eval_table_from_rows_file(wandb_backend_spy, monkeypatch, mocker):
    monkeypatch.setattr(_writer_ces, "_ROWS_FILE_THRESHOLD_BYTES", 0)
    write_wandb_rows_file = mocker.spy(_writer_ces, "_write_wandb_rows_file")

    run = _log_eval_table()

    write_wandb_rows_file.assert_called_once()
    _assert_logged_to_ces(wandb_backend_spy, run)
    assert os.listdir(os.path.join(run.settings.sync_dir, "tmp", "eval-tables")) == []
