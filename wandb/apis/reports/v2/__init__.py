import os
from inspect import cleandoc

from .... import termlog
from . import blocks, panels
from .blocks import *  # noqa
from .interface import (
    GradientPoint,
    InlineCode,
    InlineLatex,
    Layout,
    Link,
    ParallelCoordinatesPlotColumn,
    Report,
    Runset,
    RunsetGroup,
    RunsetGroupKey,
)
from .metrics import *  # noqa
from .panels import *  # noqa


def show_welcome_message():
    if os.getenv("WANDB_REPORT_API_DISABLE_MESSAGE"):
        return

    termlog(
        cleandoc(
            """
            Thanks for trying out Report API v2!
            See a tutorial and the changes here: http://wandb.me/report-api-quickstart
            For bugs/feature requests, please create an issue on github: https://github.com/wandb/wandb/issues
            You can disable this message by setting the env var WANDB_REPORT_API_DISABLE_MESSAGE=True
            """
        )
    )


show_welcome_message()
