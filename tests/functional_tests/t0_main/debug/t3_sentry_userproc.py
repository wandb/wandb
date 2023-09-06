#!/usr/bin/env python
from unittest import mock

import wandb

with mock.patch(
    "wandb.sdk.wandb_init._WandbInit.init", mock.Mock(side_effect=Exception("injected"))
):
    run = wandb.init()
