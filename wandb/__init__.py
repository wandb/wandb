from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from wandb.wandb_init import init
from wandb.wandb_setup import setup
from wandb.util import preinit as _preinit
from wandb.errors import Error
from wandb.errors.term import termlog, termerror, termwarn

#from wandb.core import *

__version__ = '0.0.1'


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
]
