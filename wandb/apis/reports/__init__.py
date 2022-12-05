# flake8: noqa
from inspect import cleandoc

from ... import termlog
from . import blocks, helpers, panels, templates
from .blocks import *
from .helpers import LineKey, PCColumn
from .panels import *
from .report import Report
from .runset import Runset
from .templates import *
from .util import InlineCode, InlineLaTeX, Link

termlog(
    cleandoc(
        """
        Thanks for trying out the Report API!
        For a tutorial, check out https://colab.research.google.com/drive/1CzyJx1nuOS4pdkXa2XPaRQyZdmFmLmXV

        Try out tab completion to see what's available.
          ∟ everything:    `wr.<tab>`
              ∟ panels:    `wr.panels.<tab>`
              ∟ blocks:    `wr.blocks.<tab>`
              ∟ helpers:   `wr.helpers.<tab>`
              ∟ templates: `wr.templates.<tab>`
              
        For bugs/feature requests, please create an issue on github: https://github.com/wandb/wandb/issues
        """
    )
)
