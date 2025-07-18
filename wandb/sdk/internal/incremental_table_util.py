from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wandb import Table
    from wandb.sdk.artifacts.artifact import Artifact

    from ..wandb_run import Run as LocalRun

ART_TYPE = "wandb-run-incremental-table"


def _get_artifact_name(run: LocalRun, key: str) -> str:
    from wandb.sdk.artifacts._internal_artifact import sanitize_artifact_name

    return sanitize_artifact_name(f"run-{run.id}-incr-{key}")


def init_artifact(run: LocalRun, sanitized_key: str) -> Artifact:
    """Initialize a new artifact for an incremental table.

    Args:
        run: The wandb run associated with this artifact
        sanitized_key: Sanitized string key to identify the table

    Returns:
        A wandb Artifact configured for incremental table storage
    """
    from wandb.sdk.artifacts._internal_artifact import InternalArtifact

    artifact = InternalArtifact(
        _get_artifact_name(run, sanitized_key),
        ART_TYPE,
        incremental=True,
    )
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
    epoch = time.time_ns() // 1_000_000
    return f"{incr_table._increment_num}-{epoch}.{key}"
