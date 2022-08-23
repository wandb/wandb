#!/usr/bin/env python
from unittest import mock

import wandb
import wandb.util


def sentry_exc(exc, delay):  # type: ignore
    return wandb.util.sentry_exc(exc, delay=0.5)


with mock.patch(
    "wandb.sdk.wandb_init._WandbInit.init",
    mock.Mock(side_effect=Exception("injected")),
), mock.patch("wandb.util.sentry_exc", sentry_exc):
    wandb.sdk.wandb_init._WandbInit.init.sentry_repr = None
    print(wandb.util.sentry_client)
    print(wandb.util.sentry_hub)
    run = wandb.init()
