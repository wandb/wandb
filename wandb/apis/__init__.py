# -*- coding: utf-8 -*-
"""
api.
"""

from wandb import util

reset_path = util.vendor_setup()

from .internal import Api as InternalApi
from .public import Api as PublicApi

reset_path()
