from __future__ import annotations

from cwsandbox._auth import AuthHeaders, register_auth_mode

import wandb
from wandb.errors import UsageError
from wandb.sdk import wandb_login, wandb_setup
from wandb.sdk.lib import wbauth

_AUTH_MODE_NAME = "wandb_sdk"


def register_wandb_auth_mode() -> None:
    """Register W&B runtime auth mode with cwsandbox's auth resolver."""
    register_auth_mode(_AUTH_MODE_NAME, _try_wandb_sdk_auth)


def _resolve_effective_entity_project() -> tuple[str | None, str | None]:
    """Resolve entity/project from the active W&B run or global settings."""
    run = _current_run()
    if run is not None:
        entity = run.entity or None
        project = run.project or None
        return entity, project

    settings = wandb_setup.singleton().settings
    entity = settings.entity or None
    project = settings.project or None
    return entity, project


def _try_wandb_sdk_auth() -> AuthHeaders | None:
    host = _current_wandb_host()
    settings = wandb_setup.singleton().settings

    auth = wbauth.session_credentials(host=host)
    if auth is None and settings.api_key:
        auth = wbauth.AuthApiKey(host=host, api_key=settings.api_key)

    if auth is None:
        _ensure_wandb_auth_loaded(host.url)
        auth = wbauth.session_credentials(host=host)

    if auth is None:
        return None

    if not isinstance(auth, wbauth.AuthApiKey):
        raise UsageError("wandb.sandbox currently supports only W&B user API-key auth.")

    entity, project = _resolve_effective_entity_project()
    metadata: list[tuple[str, str]] = [("x-api-key", auth.api_key)]
    if entity:
        metadata.append(("x-entity-id", entity))
    if project:
        metadata.append(("x-project-name", project))

    return AuthHeaders(
        headers={key: value for key, value in metadata},
        strategy="wandb_api_key",
    )


def _ensure_wandb_auth_loaded(host: str) -> None:
    """Load auth lazily using W&B's existing login path."""
    wandb_login._login(
        host=host,
        update_api_key=False,
        _silent=_should_suppress_auth_output(),
    )


def _current_run():
    """Return the best current run candidate for auth propagation."""
    if wandb.run is not None:
        return wandb.run

    return wandb_setup.singleton().most_recent_active_run


def _should_suppress_auth_output() -> bool:
    """Avoid duplicate auth output when a run is already active."""
    return _current_run() is not None


def _current_wandb_host() -> wbauth.HostUrl:
    """Return the configured W&B API host for auth resolution."""
    settings = wandb_setup.singleton().settings
    return wbauth.HostUrl(settings.base_url, app_url=settings.app_url)
