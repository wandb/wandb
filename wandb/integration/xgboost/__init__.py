# """W&B callback for xgboost

# Really simple callback to get logging for each tree

# Example usage:
"""
Use the `wandb_callback` to add `wandb` logging to any `XGboost` model. However, it will be deprecated in favor of
WandbCallback. Use it instead for more features.
"""

from .xgboost import wandb_callback, WandbCallback

__all__ = ["wandb_callback", "WandbCallback"]
