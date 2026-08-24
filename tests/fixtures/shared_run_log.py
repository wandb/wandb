"""Helpers for transaction logs flagged as shared-mode runs."""

from __future__ import annotations

import pathlib

from wandb.proto import wandb_internal_pb2  # type: ignore
from wandb.sdk.internal import datastore

SHARED_SYNC_REJECTED_FRAGMENT = "Cannot sync a shared-mode run from a transaction log"


def write_shared_run_log(
    wandb_file: pathlib.Path, *, run_id: str = "shared-run"
) -> None:
    """Write a minimal .wandb file whose RunRecord has shared=true."""
    wandb_file.parent.mkdir(parents=True, exist_ok=True)

    ds = datastore.DataStore()
    ds.open_for_write(str(wandb_file))
    rec = wandb_internal_pb2.Record()
    rec.run.run_id = run_id
    rec.run.shared = True
    ds.write(rec)
    ds.close()
