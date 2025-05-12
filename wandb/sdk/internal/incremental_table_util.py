import time
from typing import TYPE_CHECKING, Any, Dict, Optional

import wandb

if TYPE_CHECKING:
    from wandb import Table

    from ..wandb_run import Run as LocalRun
    from ..wandb_summary import Summary

ART_TYPE = "wandb-run-incremental-table"


def handle_resumed_run(incr_table: "Table", run: "LocalRun", key: str):
    """Handle different scenarios when a run is resumed.

    Check the summary to see if there was an incremental table that was logged for
    the key and assign the previous_increments_paths and increment_num to the table.
    """
    if not run.resumed or incr_table._resume_handled:
        return

    summary: Summary = run.summary

    summary_from_key: Optional[Dict[str, Any]] = summary.get(key)

    if summary_from_key is None:
        incr_table._resume_handled = True
        return

    if summary_from_key.get("_type") != "incremental-table-file":
        incr_table._resume_handled = True
        return

    incr_table._previous_increments_paths = summary_from_key.get(
        "previous_increments_paths", []
    )
    # add the artifact path of the last logged increment
    last_artifact_path = summary_from_key.get("artifact_path")
    if last_artifact_path:
        incr_table._previous_increments_paths.append(last_artifact_path)
    # add 1 because a new increment is being logged
    incr_table._increment_num = summary_from_key.get("increment_num", 0) + 1
    incr_table._resume_handled = True


def init_artifact(run: "LocalRun", sanitized_key: str):
    artifact_name = f"run-{run.id}-incr-{sanitized_key}"
    artifact = wandb.Artifact(
        artifact_name, "placeholder-run-incremental-table", incremental=True
    )
    artifact._type = ART_TYPE  # get around type restriction for system artifact
    return artifact


def get_entry_name(run: "LocalRun", incr_table: "Table", key: str):
    epoch = str(int(time.time() * 1000))
    return f"{incr_table._increment_num}-{epoch}.{key}"
