"""GraphQL stubs for sync and resume tests."""

from __future__ import annotations

import json
from typing import Any

from tests.fixtures.wandb_backend_spy.spy import WandbBackendSpy


def stub_run_resume_status(
    wandb_backend_spy: WandbBackendSpy,
    *,
    run_id: str,
    last_step: int,
    entity: str | None = None,
    storage_id: str = "storage-id",
    history_line_count: int = 0,
    history_tail_row: dict[str, Any] | None = None,
) -> None:
    """Stub ``RunResumeStatus`` for an existing run whose last step is ``last_step``."""
    gql = wandb_backend_spy.gql

    if history_tail_row is None:
        summary_metrics: dict[str, Any] = {"_step": last_step}
        history_tail = "[]"
    else:
        summary_metrics = {}
        history_tail = json.dumps([json.dumps(history_tail_row)])

    bucket: dict[str, Any] = {
        "name": run_id,
        "id": storage_id,
        "config": "{}",
        "historyLineCount": history_line_count,
        "eventsLineCount": 0,
        "logLineCount": 0,
        "eventsTail": "[]",
        "historyTail": history_tail,
        "summaryMetrics": json.dumps(summary_metrics),
        "wandbConfig": '{"t": 1}',
    }

    model: dict[str, Any] = {"bucket": bucket}
    if entity is not None:
        model["entity"] = {"name": entity}

    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="RunResumeStatus"),
        gql.once(
            content={"data": {"model": model}},
            status=200,
        ),
    )


def stub_upsert_bucket_success(
    wandb_backend_spy: WandbBackendSpy,
    *,
    run_id: str,
    entity: str = "stub-entity",
    project: str = "uncategorized",
    storage_id: str = "storage-id",
) -> None:
    """Stub successful ``UpsertBucket`` responses for the rest of the test.

    Note: filestream must also be stubbed; see stub_filestream_success.
    """
    gql = wandb_backend_spy.gql
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="UpsertBucket"),
        gql.Constant(
            content={
                "data": {
                    "upsertBucket": {
                        "bucket": {
                            "id": storage_id,
                            "name": run_id,
                            "displayName": run_id,
                            "project": {
                                "name": project,
                                "entity": {"name": entity},
                            },
                        }
                    }
                }
            },
            status=200,
        ),
    )


def stub_filestream_success(
    wandb_backend_spy: WandbBackendSpy,
    *,
    n_times: int = 64,
) -> None:
    """Stub successful FileStream responses for the rest of the test."""
    wandb_backend_spy.stub_filestream({}, status=200, n_times=n_times)


def stub_resume_for_sync(
    wandb_backend_spy: WandbBackendSpy,
    *,
    run_id: str,
    last_step: int,
    entity: str,
    project: str = "uncategorized",
) -> None:
    """Stub resume reconciliation and run upsert for beta sync of a resumed run."""
    stub_run_resume_status(
        wandb_backend_spy,
        run_id=run_id,
        last_step=last_step,
        entity=entity,
    )
    stub_upsert_bucket_success(
        wandb_backend_spy,
        run_id=run_id,
        entity=entity,
        project=project,
    )
    stub_filestream_success(wandb_backend_spy)
