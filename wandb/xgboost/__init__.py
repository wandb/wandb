"""
Compatibility fastai module.

In the future use:
    from wandb.framework.fastai import WandbCallback
"""

from wandb.framework.xgboost import wandb_callback

__all__ = ['wandb_callback']
