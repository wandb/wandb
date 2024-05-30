import wandb

try:
    from wandb_workspaces.reports.v1 import *
except ImportError:
    wandb.termerror(
        "Failed to import wandb_workspaces.  To edit reports programatically, please install it using `pip install wandb[workspaces]`."
    )
