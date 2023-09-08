"""W&B callback for xgboost.

Simple callback to get logging for each tree

Use the `wandb_callback` to add `wandb` logging to any `XGboost` model. However, it will
be deprecated in favor of WandbCallback. Use it instead for more features.
"""

from .xgboost import WandbCallback, wandb_callback

__all__ = ["wandb_callback", "WandbCallback"]
