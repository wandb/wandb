"""
Compatibility lightgbm module.

In the future use:
    from wandb.integration.lightgbm import wandb_callback
"""

from wandb.integration.lightgbm import log_summary, wandb_callback

__all__ = ["wandb_callback", "log_summary"]
