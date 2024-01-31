import os
from inspect import cleandoc

import wandb

from . import blocks, helpers, panels, templates
from .blocks import *  # noqa: F403
from .helpers import LineKey, PCColumn
from .panels import *  # noqa: F403
from .report import Report
from .runset import Runset
from .templates import *  # noqa: F403
from .util import InlineCode, InlineLaTeX, Link


def show_welcome_message():
    if os.getenv("WANDB_REPORT_API_DISABLE_MESSAGE"):
        return

    wandb.termwarn(
        cleandoc(
            """
            The v1 API is deprecated and will be removed in a future release.  Please move to v2 by setting the env var WANDB_REPORT_API_ENABLE_V2=True.  This will be on by default in a future release.
            You can disable this message by setting the env var WANDB_REPORT_API_DISABLE_MESSAGE=True
            """
        )
    )


show_welcome_message()
