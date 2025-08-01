import wandb.util as util

util.get_module("PIL.Image", lazy=True)

# ruff: noqa
import PIL.Image

assert hasattr(PIL.Image, "Image")
