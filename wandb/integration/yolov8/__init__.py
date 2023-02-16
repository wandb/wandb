"""
Tools for integrating `wandb` with [`ultralytics YOLOv8`](https://docs.ultralytics.com/),
a computer vision framework for training and deploying YOLOv8 models.
"""
from .yolov8 import WandbLogger

__all__ = ("WandbLogger",)
