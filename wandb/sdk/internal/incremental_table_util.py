import time
from typing import TYPE_CHECKING

import wandb

if TYPE_CHECKING:
    from wandb import Table
    from wandb.sdk.artifacts.artifact import Artifact
    from ..wandb_run import Run as LocalRun

ART_TYPE = "wandb-run-incremental-table"


def init_artifact(run: "LocalRun", sanitized_key: str) -> "Artifact":
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


def get_entry_name(run: "LocalRun", incr_table: "Table", key: str) -> str:
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
