import time
from typing import TYPE_CHECKING

import wandb

if TYPE_CHECKING:
    from wandb import Table

    from ..wandb_run import Run as LocalRun
    from ..wandb_summary import Summary

ART_TYPE = "wandb-run-incremental-table"

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
