"""Resolving session credentials to the account they belong to."""

from __future__ import annotations

import dataclasses
import logging
from typing import TYPE_CHECKING, Any

from wandb.sdk.lib.json_util import loads

if TYPE_CHECKING:
    from wandb.sdk.wandb_settings import Settings

_logger = logging.getLogger(__name__)

_RESOLVE_TIMEOUT_SECONDS = 5


@dataclasses.dataclass(frozen=True)
class Identity:
    """Who the W&B server says the session credentials belong to.

    This is what the server calls the "viewer": the account that the
    credentials authenticate as.
    """

    default_entity: str
    """The account's default entity, used for runs when no entity is given."""

    username: str
    """The account's username."""

    email: str
    """The account's email address."""

    teams: tuple[str, ...]
    """Names of the teams the account is a member of."""

    flags: dict[str, Any]
    """Account flags from the server, like "code_saving_enabled"."""


class SessionIdentity:
    """Lazily resolves the session credentials to an `Identity`.

    Successful resolution is cached. An instance is only valid for as long
    as the credentials in the given settings; it is meant to be discarded
    when they change.
    """

    def __init__(self, settings: Settings) -> None:
        # Imported here to avoid a circular dependency.
        from wandb.apis.public.service_api import ServiceApi

        self._settings = settings
        self._service_api = ServiceApi(
            settings=settings,
            timeout=_RESOLVE_TIMEOUT_SECONDS,
        )
        self._identity: Identity | None = None

    @property
    def identity(self) -> Identity | None:
        """The resolved identity, or None if it is not known.

        Resolved through wandb-core on first access and cached on success;
        after a failure, the next access tries again. None if the viewer
        is disabled, the session is offline, or the request failed for any
        reason including invalid credentials and connection problems.
        """
        if self._identity is None:
            self._identity = self._resolve()

        return self._identity

    def _resolve(self) -> Identity | None:
        if self._settings.x_disable_viewer or self._settings._offline:
            return None

        try:
            response = self._service_api.authenticate()
        except Exception:
            # The identity is used for informational messages and optional
            # user settings; failing to resolve it is never fatal.
            _logger.exception("Failed to resolve the session identity.")
            return None

        flags: dict[str, Any] = {}
        if response.flags_json:
            try:
                flags = loads(response.flags_json)
            except ValueError:
                _logger.warning("Ignoring invalid account flags from the server.")

        return Identity(
            default_entity=response.default_entity,
            username=response.username,
            email=response.email,
            teams=tuple(response.teams),
            flags=flags,
        )
