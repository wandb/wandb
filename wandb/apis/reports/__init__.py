from inspect import cleandoc

from ... import termlog
from . import blocks, helpers, panels
from .blocks import *
from .helpers import LineKey, PCColumn
from .panels import *
from .report import Report
from .runset import Runset

termlog(
    cleandoc(
        f"""
        Thanks for trying out the Report API!  Try out tab completion to see what's available.
          ∟ everything:  `wr.<tab>`
              ∟ panels:  `wr.panels.<tab>`
              ∟ blocks:  `wr.blocks.<tab>`
              ∟ helpers: `wr.helpers.<tab>`
        
        If you have issues, please make a ticket on JIRA.
        """
    )
)
