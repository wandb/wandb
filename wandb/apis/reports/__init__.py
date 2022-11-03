# flake8: noqa
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
        """
        Thanks for trying out the Report API!
          ∟ see panels:          \033[92m`wr.panels.<tab>`
          ∟ see blocks:          \033[92m`wr.blocks.<tab>`
          ∟ see everything else: \033[92m`wr.<tab>`
        
        If you have issues, please make a ticket on JIRA.
        """
    )
)
