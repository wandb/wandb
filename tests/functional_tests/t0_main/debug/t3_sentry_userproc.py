#!/usr/bin/env python
from unittest import mock

import wandb

with mock.patch(
    "wandb.sdk.wandb_init._WandbInit.init", mock.Mock(side_effect=Exception("injected"))
):
    wandb.sdk.wandb_init._WandbInit.init.sentry_repr = None
    run = wandb.init()
