from __future__ import annotations

import time
from typing import TYPE_CHECKING

import wandb

if TYPE_CHECKING:
    from wandb import Table
    from wandb.sdk.artifacts.artifact import Artifact

    from ..wandb_run import Run as LocalRun

ART_TYPE = "wandb-run-incremental-table"


def handle_resumed_run(incr_table: Table, run: LocalRun, key: str):
    """Set state on incrementally logged Table from resumed run.

    Handles setting recordkeeping data members to maintain continuity for
    previously logged incremental tables on the same history key.
    """
    if not run.resumed or incr_table._resume_handled:
        return

    summary = run.summary

    summary_from_key = summary.get(key)

    if (
        summary_from_key is None
        or not isinstance(summary_from_key, dict)
        or summary_from_key.get("_type") != "incremental-table-file"
    ):
        incr_table.handle_resumed_run()
        return

    previous_increments_paths = summary_from_key.get("previous_increments_paths", [])

    # add the artifact path of the last logged increment
    last_artifact_path = summary_from_key.get("artifact_path")
    if last_artifact_path:
        previous_increments_paths.append(last_artifact_path)

    # add 1 because a new increment is being logged
    increment_num = summary_from_key.get("increment_num", 0) + 1

    incr_table.handle_resumed_run(previous_increments_paths, increment_num)


def init_artifact(run: LocalRun, sanitized_key: str) -> Artifact:
    """Initialize a new artifact for an incremental table.

    Args:
        run: The wandb run associated with this artifact
        sanitized_key: Sanitized string key to identify the table

    Returns:
        A wandb Artifact configured for incremental table storage
    """
    artifact_name = f"run-{run.id}-incr-{sanitized_key}"
    artifact = wandb.Artifact(
        artifact_name,
        "placeholder-run-incremental-table",
        incremental=True,
    )
    artifact._type = ART_TYPE  # get around type restriction for system artifact
    return artifact


def get_entry_name(incr_table: Table, key: str) -> str:
    """Generate a unique entry name for a table increment.

    Args:
        run: The wandb run associated with this table
        incr_table: The incremental table being updated
        key: String key for the table entry

    Returns:
        A unique string name for the table entry
    """
    epoch = str(int(time.time() * 1000))
    return f"{incr_table._increment_num}-{epoch}.{key}"
