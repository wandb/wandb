"""Tools for integrating with [`ultralytics`](https://docs.ultralytics.com/).

Ultralytics is a computer vision framework for training and deploying YOLOv8 models.
"""

from wandb.integration.ultralytics.callback import (
    WandBUltralyticsCallback,
    add_wandb_callback,
)

__all__ = ("WandBUltralyticsCallback", "add_wandb_callback")
