"""Compatibility xgboost module.

In the future use:
    from wandb.integration.xgboost import wandb_callback
"""

from wandb.integration.xgboost import WandbCallback, wandb_callback

__all__ = ["wandb_callback", "WandbCallback"]
