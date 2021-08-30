import os
import wandb
from typing import Optional


def add_metadata(existing: Optional["UI_metadata"]) -> "UI_metadata":
    if wandb.run is not None:
        metadata = {
            "type": "web-app",
            "storage": "inline",
            "source": '<a href="{}" target="_blank">W&B Run</button>'.format(
                wandb.run.url
            ),
        }
        if existing is not None:
            existing["outputs"].append(metadata)
        else:
            return {"outputs": [metadata]}
    else:
        wandb.termwarn(
            "You must call wandb.init in the step that you call add_metadata(...)"
        )
        return {"outputs": []}