"""End-to-end tests for CES-backed EvalTables through wandb-core.

These log EvalTables against the local W&B server, with the backend spy's
fake CES in place of the CoreWeave Evaluation Service.
"""

from __future__ import annotations

import os
import urllib.parse
import uuid

import numpy as np
import pytest
import wandb
from PIL import Image as PILImage
from wandb.errors import UsageError
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


def _log_eval_table() -> wandb.Run:
    with wandb.init() as run:
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

    keys = [r.idempotency_key for r in requests]
    assert all(keys) and len(set(keys)) == len(keys), keys

    assert history[0]["eval"] == {
        "_type": "eval-table-ces",
        "schema_version": 1,
        "ncols": 5,
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


def test_logs_ces_eval_table_with_media(wandb_backend_spy, tmp_path):
    image_path = tmp_path / "cat.png"
    PILImage.new("RGB", (2, 2)).save(image_path)
    audio_path = tmp_path / "meow.wav"
    audio_path.write_bytes(b"audio")
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"video")
    image = wandb.Image(
        str(image_path),
        caption="a cat",
        boxes={
            "predictions": {
                "box_data": [
                    {
                        "position": {
                            "minX": 0.1,
                            "minY": 0.2,
                            "maxX": 0.3,
                            "maxY": 0.4,
                        },
                        "class_id": 1,
                    }
                ],
                "class_labels": {1: "cat"},
            }
        },
        masks={
            "predictions": {
                "mask_data": np.zeros((2, 2), dtype=np.uint8),
                "class_labels": {0: "background"},
            }
        },
    )

    with wandb.init() as run:
        run.log(
            {
                "eval": wandb.EvalTable(
                    columns=["image", "audio", "video"],
                    data=[
                        [
                            image,
                            wandb.Audio(str(audio_path), caption="meow"),
                            wandb.Video(str(video_path), caption="a clip"),
                        ]
                    ],
                    input_columns=["image", "audio", "video"],
                    backend="ces",
                )
            }
        )

    with wandb_backend_spy.freeze() as snapshot:
        requests = snapshot.ces_requests()
        uploaded_files = snapshot.uploaded_files(run_id=run.id)

    _, columns, rows, _ = requests
    assert [
        (field["name"], field["extension_type"])
        for field in columns.body["dataset_fields"]
    ] == [
        ("image", "wandb-image"),
        ("audio", "wandb-audio"),
        ("video", "wandb-video"),
    ]
    [row] = rows.body["rows"]
    image_value = row["input"]["image"]
    audio_value = row["input"]["audio"]
    video_value = row["input"]["video"]
    assert (image_value["caption"], audio_value["caption"], video_value["caption"]) == (
        "a cat",
        "meow",
        "a clip",
    )
    # Each value refers to a file that wandb-core uploaded to the run.
    run_file_prefix = f"wandb-run-file://{run.entity}/{run.project}/{run.id}/"
    uris = [
        image_value["uri"],
        image_value["boxes"]["predictions"]["uri"],
        image_value["masks"]["predictions"]["uri"],
        audio_value["uri"],
        video_value["uri"],
    ]
    assert all(uri.startswith(run_file_prefix) for uri in uris), uris
    assert {
        urllib.parse.unquote(uri.removeprefix(run_file_prefix)) for uri in uris
    } <= uploaded_files


def test_rejects_oversized_ces_media(wandb_backend_spy, tmp_path):
    image_path = tmp_path / "cat.png"
    PILImage.new("RGB", (2, 2)).save(image_path)
    small = wandb.Image(str(image_path), caption="a cat")
    large = wandb.Image(str(image_path), caption="a" * 3_500_000)

    with wandb.init() as run:
        with pytest.raises(UsageError, match=r"must be under 3500000 \(row 2\)"):
            run.log(
                {
                    "eval": wandb.EvalTable(
                        columns=["image"],
                        data=[[small], [large]],
                        input_columns=["image"],
                        backend="ces",
                    )
                }
            )

    with wandb_backend_spy.freeze() as snapshot:
        assert snapshot.ces_requests() == []
