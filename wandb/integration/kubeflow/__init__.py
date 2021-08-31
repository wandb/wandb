from typing import Optional

import wandb


def add_metadata(existing: Optional["UI_metadata"]) -> "UI_metadata":  # noqa: F821
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
