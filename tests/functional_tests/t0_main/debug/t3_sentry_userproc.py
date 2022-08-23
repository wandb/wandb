#!/usr/bin/env python
import sys
import time
from unittest import mock

import wandb

try:
    with mock.patch(
        "wandb.sdk.wandb_init._WandbInit.init",
        mock.Mock(side_effect=Exception("injected")),
    ):
        wandb.sdk.wandb_init._WandbInit.init.sentry_repr = None
        run = wandb.init()
except Exception as e:
    # todo: this is a hack to reduce flake
    #  (sometimes, it takes time for the mock server to pick up the sentry event)
    time.sleep(5)
    sys.exit(4294967295)
