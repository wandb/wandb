# flake8: noqa
from inspect import cleandoc

from ... import termwarn
from . import blocks, helpers, panels, templates
from .blocks import *
from .helpers import LineKey, PCColumn
from .panels import *
from .report import Report
from .runset import Runset
from .templates import *
from .util import InlineCode, InlineLaTeX, Link

termwarn(
    cleandoc(
        """
        The v1 API is deprecated and will be removed in a future release.  Please move to v2 using `import wandb.apis.reports2 as wr2`
        """
    )
)
