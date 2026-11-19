"""End-to-end tests for CES-backed EvalTables through wandb-core.

These log EvalTables against the local W&B server, with the backend spy's
fake CES in place of the CoreWeave Evaluation Service.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import pytest
import wandb
from click.testing import CliRunner
from wandb.cli import cli
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.data_types.eval_table import _writer_ces

_ROWS = [
    {
        "input": {"question": "2+2"},
        "output": {"answer": "4"},
        "scores": {"correct": True, "confidence": 0.9},
        "example_key": "q1",
    },
    {
        "input": {"question": "3+3"},
        "output": {"answer": "5"},
        "scores": {"correct": False, "confidence": 0.25},
        "example_key": "q2",
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


class _AnyUUIDv7:
    """Equals any lowercase UUIDv7 string."""

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, str):
            return False
        try:
            parsed = uuid.UUID(other)
        except ValueError:
            return False
        return parsed.version == 7 and str(parsed) == other

    def __repr__(self) -> str:
        return "<any UUIDv7>"


def _log_eval_table(mode: str = "online") -> wandb.Run:
    with wandb.init(mode=mode) as run:
        run.log(
            {
                "eval": wandb.EvalTable(
                    columns=["id", "question", "answer", "correct", "confidence"],
                    data=[
                        ["q1", "2+2", "4", True, 0.9],
                        ["q2", "3+3", "5", False, 0.25],
                    ],
                    input_columns=["question"],
                    output_columns=["answer"],
                    score_columns=["correct", "confidence"],
                    key_column="id",
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


def _assert_logged_to_ces(
    wandb_backend_spy,
    run: wandb.Run,
    *,
    offline: bool = False,
) -> None:
    """Assert CES received the table, and the run's history has its marker.

    An offline run's marker has the IDs that the client named the table and
    its first version with, and no dataset IDs.
    """
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
    assert create.body == {
        "name": "eval",
        "evaluation_id": _AnyUUIDv7(),
        "evaluation_version_id": _AnyUUIDv7(),
    }
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

    marker = {
        "_type": "eval-table-ces",
        "schema_version": 1,
        "ncols": 5,
        "nrows": 2,
        "log_mode": "IMMUTABLE",
    }
    if offline:
        marker["evaluation_id"] = create.body["evaluation_id"]
        marker["evaluation_version_id"] = create.body["evaluation_version_id"]
        assert prefix == f"wandb-eval-table-v3-{create.body['evaluation_id']}"
    else:
        marker["evaluation_id"] = "eval-id"
        marker["evaluation_version_id"] = "eval-version-id"
        marker["dataset_id"] = "dataset-id"
        marker["dataset_version_id"] = "dataset-version-id"
    assert history[0]["eval"] == marker


def test_logs_ces_eval_table(wandb_backend_spy):
    run = _log_eval_table()

    _assert_logged_to_ces(wandb_backend_spy, run)


def test_logs_ces_eval_table_from_rows_file(wandb_backend_spy, monkeypatch):
    monkeypatch.setattr(_writer_ces, "_ROWS_FILE_THRESHOLD_BYTES", 0)
    rows_files_written = 0
    write_wandb_rows_file = _writer_ces._write_wandb_rows_file

    def counting_write_wandb_rows_file(*args: Any, **kwargs: Any) -> None:
        nonlocal rows_files_written
        rows_files_written += 1
        write_wandb_rows_file(*args, **kwargs)

    monkeypatch.setattr(
        _writer_ces, "_write_wandb_rows_file", counting_write_wandb_rows_file
    )

    run = _log_eval_table()

    assert rows_files_written == 1
    _assert_logged_to_ces(wandb_backend_spy, run)
    assert os.listdir(os.path.join(run.settings.sync_dir, "tmp", "eval-tables")) == []


@pytest.mark.parametrize("rows_file", [False, True], ids=["inline", "rows_file"])
def test_syncs_ces_eval_table_from_offline_run(
    wandb_backend_spy,
    runner: CliRunner,
    monkeypatch,
    rows_file: bool,
):
    if rows_file:
        monkeypatch.setattr(_writer_ces, "_ROWS_FILE_THRESHOLD_BYTES", 0)

    run = _log_eval_table(mode="offline")
    with wandb_backend_spy.freeze() as snapshot:
        assert snapshot.ces_requests() == []

    result = runner.invoke(cli.sync, [run.settings.sync_dir])

    assert result.exit_code == 0, result.output
    _assert_logged_to_ces(wandb_backend_spy, run, offline=True)
    if rows_file:
        staging_dir = os.path.join(run.settings.sync_dir, "tmp", "eval-tables")
        assert os.listdir(staging_dir) == []
        # `wandb sync` can upload the table again from the copy it keeps.
        record_dir = os.path.join(run.settings.sync_dir, "eval-tables")
        assert len(os.listdir(record_dir)) == 1
