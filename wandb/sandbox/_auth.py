from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from cwsandbox import AuthHeaders, CWSandboxAuthenticationError, set_auth_mode

import wandb
from wandb.errors import UsageError
from wandb.sdk import wandb_login, wandb_setup
from wandb.sdk.lib import wbauth

_AUTH_MODE_NAME = "wandb"
_OVERRIDE_UNSET = object()
_entity_override: ContextVar[object | str] = ContextVar(
    "wandb_sandbox_entity_override",
    default=_OVERRIDE_UNSET,
)


def _set_wandb_auth_mode() -> None:
    """Install W&B as the active cwsandbox auth mode for this process.

    NOTE: This means the original cwsandbox auth using sandbox api key no longer works.
    """
    set_auth_mode(_AUTH_MODE_NAME, _resolve_wandb_sdk_auth)


@contextmanager
def _override_sandbox_entity(
    entity: str | None = None,
) -> Iterator[None]:
    """Temporarily override the sandbox entity for sandbox auth.

    Passing ``None`` means using the default resolve logic from run
    and setting. Only used by the cli to set entity via --entity.
    """
    if entity is None:
        yield
        return

    entity_token = _entity_override.set(entity)
    try:
        yield
    finally:
        _entity_override.reset(entity_token)


def _resolve_entity_project() -> tuple[str | None, str | None]:
    """Resolve entity/project from overrides, the active run, or global settings."""
    entity_override = _entity_override.get()
    if isinstance(entity_override, str):
        # None project is fine because the override is only used by cli, which does not
        # support project for when filtering sandbox.
        return entity_override, None

    run = wandb.run or wandb_setup.singleton().most_recent_active_run
    if run is not None:
        return run.entity or None, run.project or None

    settings = wandb_setup.singleton().settings
    return settings.entity or None, settings.project or None


def _resolve_wandb_sdk_auth() -> AuthHeaders:
    settings = wandb_setup.singleton().settings
    host = wbauth.HostUrl(settings.base_url, app_url=settings.app_url)

    auth = wbauth.session_credentials(host=host)
    if auth is None and settings.api_key:
        auth = wbauth.AuthApiKey(host=host, api_key=settings.api_key)

    if auth is None:
        run = wandb.run or wandb_setup.singleton().most_recent_active_run
        wandb_login._login(
            host=host.url,
            update_api_key=False,
            _silent=run is not None,
        )
        auth = wbauth.session_credentials(host=host)

    if auth is None:
        raise CWSandboxAuthenticationError(
            "wandb.sandbox could not resolve W&B credentials for sandbox auth."
        )

    if not isinstance(auth, wbauth.AuthApiKey):
        raise UsageError("wandb.sandbox currently supports only W&B user API-key auth.")

    entity, project = _resolve_entity_project()
    metadata: list[tuple[str, str]] = [("x-api-key", auth.api_key)]
    # Both entity and project are optional.
    # entity will use the default entity user set in web UI.
    # project will use/create 'sandbox' project automatically.
    if entity:
        metadata.append(("x-entity-id", entity))
    if project:
        metadata.append(("x-project-name", project))

    return AuthHeaders(
        headers={key: value for key, value in metadata},
        strategy="wandb_api_key",
    )
