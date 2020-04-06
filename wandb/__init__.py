# -*- coding: utf-8 -*-
"""
module init
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

__version__ = '0.0.19'

import sys

from wandb.errors import Error


PY3 = sys.version_info.major == 3 and sys.version_info.minor >= 6
if PY3:
    TYPE_CHECKING = True
    from wandb import sdk as wandb_sdk
else:
    TYPE_CHECKING = False
    from wandb import sdk_py27 as wandb_sdk

init = wandb_sdk.init
setup = wandb_sdk.setup
save = wandb_sdk.save
watch = wandb_sdk.watch
login = wandb_sdk.login
Settings = wandb_sdk.Settings

from wandb.util import preinit as _preinit
from wandb.util import lazyloader as _lazyloader
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

keras = _lazyloader.LazyLoader('wandb.keras', globals(), 'wandb.framework.keras')

__all__ = [
    "__version__",
    "init",
    "setup",
    "save",
]
