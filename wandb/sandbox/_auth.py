from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from cwsandbox import AuthHeaders, CWSandboxAuthenticationError, set_auth_mode

from wandb.errors import UsageError
from wandb.sdk import wandb_setup
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
def override_sandbox_entity(
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


def _resolve_wandb_sdk_auth() -> AuthHeaders:
    settings = wandb_setup.singleton().settings
    host = wbauth.HostUrl(settings.base_url, app_url=settings.app_url)
    auth = wbauth.authenticate_session(host=host, source="sandbox", no_offline=True)
    if auth is None:
        raise CWSandboxAuthenticationError(
            "wandb.sandbox could not resolve W&B credentials for sandbox auth."
        )
    if not isinstance(auth, wbauth.AuthApiKey):
        raise UsageError("wandb.sandbox currently supports only W&B user API-key auth.")

    metadata: list[tuple[str, str]] = [("x-api-key", auth.api_key)]
    # Both entity and project are optional.
    # entity will use the default entity user set in web UI.
    # project will use/create 'sandbox' project automatically.
    entity = settings.entity
    # entity can be set by --entity cli flag via override_sandbox_entity
    entity_override = _entity_override.get()
    if isinstance(entity_override, str):
        entity = entity_override
    if entity:
        metadata.append(("x-entity-id", entity))
    if settings.project:
        metadata.append(("x-project-name", settings.project))

    return AuthHeaders(
        headers={key: value for key, value in metadata},
        strategy="wandb_api_key",
    )
