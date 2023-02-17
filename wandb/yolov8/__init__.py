"""
Compatibility yolov8 module

In the future use e.g.:
    from wandb.integration.yolov8 import WandbLogger
"""

from wandb.integration.yolov8 import WandbLogger, add_callbacks

__all__ = ("WandbLogger", "add_callbacks")
