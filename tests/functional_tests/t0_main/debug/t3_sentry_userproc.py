#!/usr/bin/env python
from unittest import mock


def sentry_exc(exc, delay):  # type: ignore
    import wandb.util

    return wandb.util.sentry_exc(exc, delay=2)


with mock.patch(
    "wandb.sdk.wandb_init._WandbInit.init",
    mock.Mock(side_effect=Exception("injected")),
), mock.patch("wandb.util.sentry_exc", sentry_exc):
    import wandb

    wandb.sdk.wandb_init._WandbInit.init.sentry_repr = None
    wandb.termwarn(wandb.util.sentry_client)
    wandb.termwarn(wandb.util.sentry_hub)
    run = wandb.init()
