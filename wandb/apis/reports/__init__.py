# flake8: noqa

from .blocks import *
from .panels import *
from .reports import LineKey, PCColumn, Report, Runset
from ... import termlog
from inspect import cleandoc

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
