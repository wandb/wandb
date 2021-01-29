# -*- coding: utf-8 -*-
"""
api.
"""

from wandb import util

from .internal import Api as InternalApi
from .public import Api as PublicApi


reset_path = util.vendor_setup()
reset_path()


__all__ = ["InternalApi", "PublicApi"]
