# -*- coding: utf-8 -*-
"""
api.
"""

from wandb import util

util.vendor_setup()

from .internal import Api as InternalApi
from .public import Api as PublicApi

# Is there a better way to get public modules into wandb_artifacts?
# I feel like I should not need to to this.
from .public import Artifact as PublicArtifact
