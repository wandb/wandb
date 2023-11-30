__all__ = ("autolog", "WandbLogger")

import wandb
from wandb import util

_openai = util.get_module("openai")

from pkg_resources import parse_version

from .openai import autolog

if _openai:
    if parse_version(_openai.__version__) > parse_version("1.0.1"):
        from .fine_tune import WandbLogger
else:
    wandb.termerror(
        "`openai` is not installed or your current `openai` version is {openai_version}. "
        "This integration requires openai version 1.0.1 and above. "
        "To fix, please `pip install openai`"
    )
