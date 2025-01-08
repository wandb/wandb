import wandb

try:
    from wandb_workspaces.workspaces import *  # noqa: F403
except ImportError:
    wandb.termerror(
        "Failed to import wandb_workspaces. To edit workspaces programmatically, please install it using `pip install wandb[workspaces]`."
    )
