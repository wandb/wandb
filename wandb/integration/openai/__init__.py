__all__ = ("autolog", "WandbLogger")

from wandb import util

openai = util.get_module("openai")

from pkg_resources import parse_version

from .openai import autolog

if parse_version(openai.__version__) > parse_version("0.28.1"):
    from .fine_tune import WandbLogger
