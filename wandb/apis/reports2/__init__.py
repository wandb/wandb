import os
from inspect import cleandoc

from ... import termlog
from . import blocks, panels
from .blocks import *  # noqa
from .interface import (
    GradientPoint,
    Group,
    InlineCode,
    InlineLatex,
    Layout,
    Link,
    ParallelCoordinatesPlotColumn,
    Report,
    Runset,
)
from .metrics import *  # noqa
from .panels import *  # noqa


def show_welcome_message():
    if os.getenv("WANDB_DISABLE_REPORT_API_MESSAGE"):
        return

    termlog(
        cleandoc(
            """
            Thanks for trying out Report API v2!
            See a tutorial and the changes here: https://colab.research.google.com/drive/1CzyJx1nuOS4pdkXa2XPaRQyZdmFmLmXV
            For bugs/feature requests, please create an issue on github: https://github.com/wandb/wandb/issues
            """
        )
    )


show_welcome_message()
