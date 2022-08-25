#!/usr/bin/env python
from unittest import mock


def sentry_exc(exc, delay):  # type: ignore
    import wandb.util

    return wandb.util.sentry_exc(exc, delay=5)


def _send_request(self, body, headers, endpoint_type="store", envelope=None):  # type: ignore
    # unzip bytes and decode to string
    import gzip

    data = gzip.decompress(body).decode("utf-8")
    print(data)


with mock.patch(
    "wandb.sdk.wandb_init._WandbInit.init",
    mock.Mock(side_effect=Exception("injected")),
), mock.patch("wandb.util.sentry_exc", sentry_exc,), mock.patch(
    "sentry_sdk.transport.HttpTransport._send_request",
    _send_request,
):
    import wandb

    wandb.sdk.wandb_init._WandbInit.init.sentry_repr = None
    wandb.termwarn(str(wandb.util.sentry_client))
    wandb.termwarn(str(wandb.util.sentry_hub))
    run = wandb.init()
