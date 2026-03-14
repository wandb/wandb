"""W&B-specific auth resolution for `wandb.sandbox`.

We keep this logic local to the W&B wrapper instead of monkeypatching
`cwsandbox._sandbox.resolve_auth_metadata` process-wide.

That patch-based approach would reduce copied code, but it would also make
direct `cwsandbox` usage in the same Python process pick up W&B-specific auth
behavior unexpectedly after `import wandb.sandbox`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import wandb
from wandb.errors import UsageError
from wandb.sdk import wandb_login, wandb_setup
from wandb.sdk.lib import wbauth

WANDB_CLOUD_BASE_URL = "https://api.wandb.ai"


@dataclass(frozen=True)
class SandboxAuthContext:
    metadata: tuple[tuple[str, str], ...]
    strategy: str
    entity: str | None = None
    project: str | None = None


def resolve_auth_context() -> SandboxAuthContext:
    """Resolve auth metadata for `wandb.sandbox`.

    Resolution order:
    1. Explicit `CWSANDBOX_API_KEY`
    2. In-memory W&B session auth
    3. Loaded W&B settings api_key
    4. Lazy W&B login/auth resolution

    TODO: If `cwsandbox` exposes protected auth hooks for instance and class
    operations, this wrapper can delegate more directly instead of maintaining
    its own auth-resolution entry point.
    """
    cwsandbox_api_key = os.environ.get("CWSANDBOX_API_KEY")
    if cwsandbox_api_key:
        return SandboxAuthContext(
            metadata=(("authorization", f"Bearer {cwsandbox_api_key}"),),
            strategy="cwsandbox_api_key",
        )

    settings = wandb_setup.singleton().settings
    if settings.base_url.rstrip("/") != WANDB_CLOUD_BASE_URL:
        raise UsageError(
            "wandb.sandbox currently supports only the managed wandb.ai auth flow."
        )

    auth = wbauth.session_credentials(host=WANDB_CLOUD_BASE_URL)
    if auth is None and settings.api_key:
        auth = wbauth.AuthApiKey(host=WANDB_CLOUD_BASE_URL, api_key=settings.api_key)

    if auth is None:
        _ensure_wandb_auth_loaded()
        auth = wbauth.session_credentials(host=WANDB_CLOUD_BASE_URL)

    if auth is None:
        raise UsageError("No W&B API key configured. Use `wandb.login()` first.")

    if not isinstance(auth, wbauth.AuthApiKey):
        raise UsageError("wandb.sandbox currently supports only W&B user API-key auth.")

    entity, project = resolve_effective_entity_project()
    metadata: list[tuple[str, str]] = [("x-api-key", auth.api_key)]
    if entity:
        metadata.append(("x-entity-id", entity))
    if project:
        metadata.append(("x-project-name", project))

    return SandboxAuthContext(
        metadata=tuple(metadata),
        strategy="wandb_api_key",
        entity=entity,
        project=project,
    )


def resolve_cwsandbox_metadata() -> tuple[tuple[str, str], ...]:
    """Resolve gRPC metadata for `cwsandbox` RPCs."""
    return resolve_auth_context().metadata


def resolve_effective_entity_project() -> tuple[str | None, str | None]:
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


def _ensure_wandb_auth_loaded() -> None:
    """Load auth lazily using W&B's existing login path."""
    wandb_login._login(
        host=WANDB_CLOUD_BASE_URL,
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
