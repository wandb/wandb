"""Compatibility wandb_run module.

Please use `wandb.Run` instead.
"""

from wandb.sdk.wandb_run import Run

__all__ = ["Run"]
