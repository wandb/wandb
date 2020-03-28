# -*- coding: utf-8 -*-
"""
module init
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

__version__ = '0.0.14'

from wandb.errors import Error

import sys
if sys.version_info < (3, 0):
    from wandb.sdk_py27.wandb_init import init
    from wandb.sdk_py27.wandb_setup import setup
    from wandb.sdk_py27.wandb_save import save
    from wandb.sdk_py27.wandb_watch import watch
    from wandb.sdk_py27.wandb_login import login
else:
    from wandb.sdk.wandb_init import init
    from wandb.sdk.wandb_setup import setup
    from wandb.sdk.wandb_save import save
    from wandb.sdk.wandb_watch import watch
    from wandb.sdk.wandb_login import login

from wandb.util import preinit as _preinit
from wandb.errors.term import termlog, termerror, termwarn

# Move this (keras.__init__ expects it at top level)
from wandb.data.data_types import Graph
from wandb.data.data_types import Image
from wandb.data.data_types import Video
from wandb.data.data_types import Audio
from wandb.data.data_types import Table
from wandb.data.data_types import Html
from wandb.data.data_types import Object3D
from wandb.data.data_types import Molecule
from wandb.data.data_types import Histogram
from wandb.data.data_types import Graph


from wandb import agent
#from wandb.core import *

# toplevel:
# save()
# restore()
# login()
# sweep()
# agent()

# globals
run = None
config = _preinit.PreInitObject("wandb.config")
summary = _preinit.PreInitObject("wandb.summary")
log = _preinit.PreInitCallable("wandb.log")
join = _preinit.PreInitCallable("wandb.join")

__all__ = [
    "__version__",
    "init",
    "setup",
    "save",
]
