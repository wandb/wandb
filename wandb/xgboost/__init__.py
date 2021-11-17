"""
Compatibility xgboost module.

In the future use:
    from wandb.integration.xgboost import wandb_callback
"""

from wandb.integration.xgboost import wandb_callback, WandbCallback

__all__ = ["wandb_callback", "WandbCallback"]
