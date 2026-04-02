from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from cwsandbox import AuthHeaders, CWSandboxAuthenticationError, set_auth_mode

import wandb
from wandb.errors import UsageError
from wandb.sdk import wandb_login, wandb_setup
from wandb.sdk.lib import wbauth

_AUTH_MODE_NAME = "wandb_sdk"
_OVERRIDE_UNSET = object()
_entity_override: ContextVar[object | str | None] = ContextVar(
    "wandb_sandbox_entity_override",
    default=_OVERRIDE_UNSET,
)
_project_override: ContextVar[object | str | None] = ContextVar(
    "wandb_sandbox_project_override",
    default=_OVERRIDE_UNSET,
)


def register_wandb_auth_mode() -> None:
    """Install W&B as the active cwsandbox auth mode for this process."""
    set_auth_mode(_AUTH_MODE_NAME, _resolve_wandb_sdk_auth)


@contextmanager
def override_auth_context(
    *,
    entity: object | str | None = _OVERRIDE_UNSET,
    project: object | str | None = _OVERRIDE_UNSET,
) -> Iterator[None]:
    """Temporarily override entity/project propagation for sandbox auth.

    Any field left unset is suppressed while the override is active so CLI
    overrides do not accidentally inherit the current run or global defaults.
    """
    entity_token = _entity_override.set(entity)
    project_token = _project_override.set(project)
    try:
        yield
    finally:
        _entity_override.reset(entity_token)
        _project_override.reset(project_token)


def _resolve_effective_entity_project() -> tuple[str | None, str | None]:
    """Resolve entity/project from overrides, the active run, or global settings."""
    override = _current_override()
    if override is not None:
        return override

    run = _current_run()
    if run is not None:
        entity = run.entity or None
        project = run.project or None
        return entity, project

    settings = wandb_setup.singleton().settings
    entity = settings.entity or None
    project = settings.project or None
    return entity, project


def _current_override() -> tuple[str | None, str | None] | None:
    entity = _entity_override.get()
    project = _project_override.get()
    if entity is _OVERRIDE_UNSET and project is _OVERRIDE_UNSET:
        return None

    resolved_entity = None if entity is _OVERRIDE_UNSET else entity
    resolved_project = None if project is _OVERRIDE_UNSET else project
    return resolved_entity, resolved_project


def _resolve_wandb_sdk_auth() -> AuthHeaders:
    host = _current_wandb_host()
    settings = wandb_setup.singleton().settings

    auth = wbauth.session_credentials(host=host)
    if auth is None and settings.api_key:
        auth = wbauth.AuthApiKey(host=host, api_key=settings.api_key)

    if auth is None:
        _ensure_wandb_auth_loaded(host.url)
        auth = wbauth.session_credentials(host=host)

    if auth is None:
        raise CWSandboxAuthenticationError(
            "wandb.sandbox could not resolve W&B credentials for sandbox auth."
        )

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
