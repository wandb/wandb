"""SandboxSession — aviato.Session subclass with W&B integration."""

from __future__ import annotations

import logging
import re
import threading
from typing import Any

import aviato

import wandb

logger = logging.getLogger(__name__)


def _get_wandb_env() -> dict[str, str]:
    """Build dict of W&B env vars to inject, or empty dict if no active run."""
    run = wandb.run
    if run is None:
        return {}

    env: dict[str, str] = {}

    api_key = run._settings.api_key
    if api_key:
        env["WANDB_API_KEY"] = api_key

    if run.entity:
        env["WANDB_ENTITY"] = run.entity

    if run.project:
        env["WANDB_PROJECT"] = run.project

    base_url = run._settings.base_url
    if base_url and base_url != "https://api.wandb.ai":
        env["WANDB_BASE_URL"] = base_url

    return env


def _is_valid_k8s_label(value: str) -> bool:
    """Check if a string is a valid Kubernetes label value."""
    if not value or len(value) > 63:
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?", value))


def _get_wandb_run_tag() -> str | None:
    """Return a K8s-safe tag like ``wandb-<run-name>``, or None if not usable."""
    run = wandb.run
    if run is None or not run.name:
        return None
    tag = f"wandb-{run.name}"
    if not _is_valid_k8s_label(tag):
        logger.warning(
            "Skipping aviato sandbox tagging: run name %r produces "
            "invalid K8s label %r",
            run.name,
            tag,
        )
        return None
    return tag


def _log_sandbox_id(sandbox_id: str) -> None:
    """Log a single sandbox ID to the active wandb run."""
    run = wandb.run
    if run is None:
        return

    try:
        run.log({"aviato/sandbox_id": sandbox_id})
        logger.debug("Logged aviato sandbox %s to wandb", sandbox_id)
    except Exception as e:
        logger.warning("Failed to log aviato sandbox ID to wandb: %s", e)


class SandboxSession(aviato.Session):
    """aviato.Session with automatic W&B integration.

    Extends ``aviato.Session`` so that an active ``wandb.run`` automatically:

    1. Injects W&B credentials (``WANDB_API_KEY``, ``WANDB_ENTITY``,
       ``WANDB_PROJECT``) as environment variables into every sandbox.
    2. Tags sandboxes with the wandb run name.
    3. Logs each sandbox ID to the wandb run on start.

    User-provided environment variables and tags always take precedence.

    Example::

        run = wandb.init(project="my-project")
        with run.SandboxSession() as session:
            sb = session.sandbox(container_image="python:3.11")
    """

    def __init__(
        self,
        defaults: aviato.SandboxDefaults | None = None,
        report_to: list[str] | None = None,
    ) -> None:
        defaults = defaults or aviato.SandboxDefaults()

        # Inject W&B env vars underneath user-provided ones
        wandb_env = _get_wandb_env()
        if wandb_env:
            merged_env = {**wandb_env, **defaults.environment_variables}
            defaults = defaults.with_overrides(environment_variables=merged_env)

        super().__init__(defaults=defaults, report_to=report_to)

    def __enter__(self) -> SandboxSession:
        self._tag_defaults()
        return super().__enter__()  # type: ignore[return-value]

    async def __aenter__(self) -> SandboxSession:
        self._tag_defaults()
        return await super().__aenter__()  # type: ignore[return-value]

    def sandbox(self, **kwargs: Any) -> aviato.Sandbox:
        sb = super().sandbox(**kwargs)
        self._hook_sandbox_start(sb)
        return sb

    def _tag_defaults(self) -> None:
        """Add wandb run name tag to session defaults."""
        tag = _get_wandb_run_tag()
        if tag is None:
            return

        existing_tags = self._defaults.tags
        if tag not in existing_tags:
            self._defaults = self._defaults.with_overrides(
                tags=(*existing_tags, tag),
            )

    def _hook_sandbox_start(self, sb: aviato.Sandbox) -> None:
        """Hook into sandbox start to log sandbox_id to wandb."""
        original_start = sb._start_async

        async def _patched_start() -> str:
            sandbox_id = await original_start()
            # Fire-and-forget — don't block sandbox creation
            threading.Thread(
                target=_log_sandbox_id, args=(sandbox_id,), daemon=True
            ).start()
            return sandbox_id

        sb._start_async = _patched_start  # type: ignore[assignment]
