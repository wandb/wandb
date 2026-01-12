"""Compatibility wandb_run module.

Please use `wandb.Run` instead.
"""

from __future__ import annotations

from wandb.sdk.wandb_run import Run

__all__ = ["Run"]
