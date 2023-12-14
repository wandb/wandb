"""Compatibility catboost module.

In the future use:
    from wandb.integration.catboost import WandbCallback
"""

from wandb.integration.catboost import WandbCallback, log_summary

__all__ = ["log_summary", "WandbCallback"]
