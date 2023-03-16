"""Tools for integrating `wandb` with [`ultralytics YOLOv8`](https://docs.ultralytics.com/).

YOLOv8 is a computer vision framework for training and deploying YOLOv8 models.
"""
__all__ = ("add_callbacks",)

from .yolov8 import add_callbacks
