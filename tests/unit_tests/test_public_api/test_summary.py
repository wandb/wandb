import json
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from wandb.apis.public.summary import HTTPSummary, Summary


def _run(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        dir=str(tmp_path),
        id="run-id",
        entity="entity",
        project="project",
        storage_id="storage-id",
        path=["entity", "project", "run-id"],
    )


def test_nested_summary_reads_values(tmp_path: Path):
    summary = Summary(_run(tmp_path), {"a": {"b": {"c": 0.9}}})

    assert summary["a"]["b"]["c"] == 0.9


def test_http_summary_update_uses_service_api(tmp_path: Path):
    service_api = mock.Mock()
    service_api.execute_graphql.return_value = {
        "upsertBucket": {"bucket": {"id": "storage-id"}}
    }

    summary = HTTPSummary(_run(tmp_path), service_api, summary={})
    summary.update({"metric": 1})

    service_api.execute_graphql.assert_called_once()
    _, kwargs = service_api.execute_graphql.call_args
    assert kwargs["variables"]["id"] == "storage-id"
    assert json.loads(kwargs["variables"]["summaryMetrics"]) == {"metric": 1}
