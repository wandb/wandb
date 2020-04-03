"""
Compatibility keras module.

In the future use:
    from wandb.framework.keras import WandbCallback
"""

from wandb.framework.keras import WandbCallback  # type: ignore

__all__ = ['WandbCallback']
