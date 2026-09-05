"""The deprecated `wandb.api` object and `wandb.ensure_configured()`."""

from __future__ import annotations

import os
from typing import Any

import wandb
from wandb import env
from wandb.proto.wandb_telemetry_pb2 import Deprecated
from wandb.sdk import wandb_setup
from wandb.sdk.lib import wbauth
from wandb.sdk.lib.deprecation import warn_and_record_deprecation

_MESSAGE = (
    "wandb.api and wandb.ensure_configured() are deprecated and will be removed"
    " in a future release. To check for credentials without prompting,"
    " use wandb.login(prompt=False)."
)


def _warn(message: str) -> None:
    warn_and_record_deprecation(feature=Deprecated(wandb_api=True), message=message)


class DeprecatedApi:
    """The object behind `wandb.api`.

    Only `api_key`, `default_entity` and `viewer()` remain.
    """

    @property
    def api_key(self) -> str | None:
        _warn(_MESSAGE)
        host = wandb_setup.singleton().settings.base_url
        auth = wbauth.session_credentials(host=host)
        if isinstance(auth, wbauth.AuthApiKey):
            return auth.api_key
        return os.getenv(env.API_KEY) or wbauth.read_netrc_auth(host=host)

    @property
    def default_entity(self) -> str | None:
        _warn(
            "wandb.api.default_entity is deprecated,"
            " use wandb.Api().default_entity instead."
        )
        return wandb.Api().default_entity

    def viewer(self) -> dict[str, Any]:
        _warn(
            "wandb.api.viewer() is deprecated, use wandb.Api().viewer.entity instead."
        )
        return dict(wandb.Api().viewer._attrs)


def ensure_configured() -> None:
    """Deprecated and does nothing. `wandb.api.api_key` is looked up on access."""
    _warn(_MESSAGE)
