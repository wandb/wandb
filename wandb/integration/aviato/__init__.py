"""Aviato integration for W&B.

Monkeypatches aviato so that an active ``wandb.run`` automatically:

1. Injects W&B credentials (``WANDB_API_KEY``, ``WANDB_ENTITY``,
   ``WANDB_PROJECT``) as environment variables into **every** sandbox
   — via ``SandboxDefaults.merge_environment_variables``.
2. Tags sandboxes with the wandb run ID — via ``Session.__enter__``.
3. Logs each sandbox ID to the wandb run as soon as the backend
   accepts it — via ``Sandbox._start_async``.

Usage::

    import aviato
    import wandb

    with wandb.init(project="my-project") as run:
        with aviato.Session() as session:
            sb = session.sandbox(...)
            # sb has WANDB_API_KEY, WANDB_ENTITY, WANDB_PROJECT
            # sb is tagged with the wandb run ID
            # sb's sandbox_id is logged to wandb immediately on start

Activation:
    - Automatic: called from ``wandb.init()``.  If aviato is already
      imported, patches immediately.  If not, registers an import hook
      so the patch fires whenever ``import aviato`` happens later.
    - Manual: ``from wandb.integration.aviato import patch; patch()``.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def setup() -> None:
    """Auto-setup called from ``wandb.init()``.

    If aviato is already imported, patches immediately.  Otherwise
    registers an import hook so the patch fires on first
    ``import aviato``.
    """
    if "aviato" in sys.modules:
        try:
            patch()
        except Exception as e:
            logger.warning("Failed to auto-patch aviato: %s", e)
    else:
        from wandb.util import add_import_hook

        def _on_aviato_import() -> None:
            try:
                patch()
            except Exception as e:
                logger.warning("Failed to auto-patch aviato: %s", e)

        add_import_hook("aviato", _on_aviato_import)


def patch() -> None:
    """Monkeypatch aviato to integrate with W&B.

    Safe to call multiple times — subsequent calls are no-ops.

    Raises:
        ImportError: If aviato is not installed.
    """
    import aviato

    if getattr(aviato.Session, "_wandb_patched", False):
        return

    _patch_merge_environment_variables(aviato)
    _patch_session_enter(aviato)
    _patch_sandbox_start(aviato)

    aviato.Session._wandb_patched = True  # type: ignore[attr-defined]
    logger.debug("Patched aviato with W&B integration")


def unpatch() -> None:
    """Restore original aviato methods."""
    try:
        import aviato
    except ImportError:
        return

    if not getattr(aviato.Session, "_wandb_patched", False):
        return

    _unpatch_merge_environment_variables(aviato)
    _unpatch_session_enter(aviato)
    _unpatch_sandbox_start(aviato)

    del aviato.Session._wandb_patched  # type: ignore[attr-defined]
    logger.debug("Unpatched aviato")


# ---------------------------------------------------------------------------
# 1. Environment variable injection (SandboxDefaults.merge_environment_variables)
# ---------------------------------------------------------------------------


def _get_wandb_env() -> dict[str, str]:
    """Build dict of W&B env vars to inject, or empty dict if no active run."""
    import wandb

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


def _patch_merge_environment_variables(aviato: Any) -> None:
    defaults_cls = aviato.SandboxDefaults
    original = defaults_cls.merge_environment_variables

    def _patched_merge(self: Any, additional: dict[str, str] | None) -> dict[str, str]:
        # Original merge: defaults ← additional (additional wins)
        merged = original(self, additional)
        # Inject wandb env vars underneath — user/additional values win
        wandb_env = _get_wandb_env()
        if wandb_env:
            merged = {**wandb_env, **merged}
        return merged

    defaults_cls._wandb_original_merge_env = original  # type: ignore[attr-defined]
    defaults_cls.merge_environment_variables = _patched_merge  # type: ignore[assignment]


def _unpatch_merge_environment_variables(aviato: Any) -> None:
    defaults_cls = aviato.SandboxDefaults
    if hasattr(defaults_cls, "_wandb_original_merge_env"):
        defaults_cls.merge_environment_variables = (
            defaults_cls._wandb_original_merge_env
        )
        del defaults_cls._wandb_original_merge_env


# ---------------------------------------------------------------------------
# 2. Session.__enter__ — tag sandboxes with the wandb run ID
# ---------------------------------------------------------------------------


def _is_valid_k8s_label(value: str) -> bool:
    """Check if a string is a valid Kubernetes label value.

    K8s labels must match ``([A-Za-z0-9][-A-Za-z0-9_.]*)?[A-Za-z0-9]``:
    alphanumeric, hyphens, underscores, dots; must start and end with
    an alphanumeric character; max 63 chars.
    """
    import re

    if not value or len(value) > 63:
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?", value))


def _get_wandb_run_tag() -> str | None:
    """Return a K8s-safe tag like ``wandb-<run-name>``, or None if not usable.

    Returns None (skips tagging) if the run name produces an invalid
    Kubernetes label value — better to skip than to silently mangle.
    """
    import wandb

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


def _patch_session_enter(aviato: Any) -> None:
    original_enter = aviato.Session.__enter__
    original_aenter = aviato.Session.__aenter__

    def _patched_enter(self: Any) -> Any:
        _tag_session_defaults(self)
        return original_enter(self)

    async def _patched_aenter(self: Any) -> Any:
        _tag_session_defaults(self)
        return await original_aenter(self)

    aviato.Session._wandb_original_enter = original_enter  # type: ignore[attr-defined]
    aviato.Session._wandb_original_aenter = original_aenter  # type: ignore[attr-defined]
    aviato.Session.__enter__ = _patched_enter  # type: ignore[assignment]
    aviato.Session.__aenter__ = _patched_aenter  # type: ignore[assignment]


def _unpatch_session_enter(aviato: Any) -> None:
    if hasattr(aviato.Session, "_wandb_original_enter"):
        aviato.Session.__enter__ = aviato.Session._wandb_original_enter
        aviato.Session.__aenter__ = aviato.Session._wandb_original_aenter
        del aviato.Session._wandb_original_enter
        del aviato.Session._wandb_original_aenter


def _tag_session_defaults(session: Any) -> None:
    """Add wandb run ID tag to session defaults."""
    tag = _get_wandb_run_tag()
    if tag is None:
        return

    existing_tags = session._defaults.tags
    if tag not in existing_tags:
        session._defaults = session._defaults.with_overrides(
            tags=(*existing_tags, tag),
        )


# ---------------------------------------------------------------------------
# 3. Sandbox._start_async — log sandbox ID as soon as it's available
# ---------------------------------------------------------------------------


def _patch_sandbox_start(aviato: Any) -> None:
    sandbox_cls = aviato.Sandbox
    original_start = sandbox_cls._start_async

    async def _patched_start(self: Any) -> str:
        sandbox_id = await original_start(self)
        # Fire-and-forget — don't block sandbox creation on wandb logging
        import threading

        threading.Thread(
            target=_log_sandbox_id, args=(sandbox_id,), daemon=True
        ).start()
        return sandbox_id

    sandbox_cls._wandb_original_start_async = original_start  # type: ignore[attr-defined]
    sandbox_cls._start_async = _patched_start  # type: ignore[assignment]


def _unpatch_sandbox_start(aviato: Any) -> None:
    sandbox_cls = aviato.Sandbox
    if hasattr(sandbox_cls, "_wandb_original_start_async"):
        sandbox_cls._start_async = sandbox_cls._wandb_original_start_async
        del sandbox_cls._wandb_original_start_async


def _log_sandbox_id(sandbox_id: str) -> None:
    """Log a single sandbox ID to the active wandb run."""
    import wandb

    run = wandb.run
    if run is None:
        return

    try:
        run.log({"aviato/sandbox_id": sandbox_id})
        logger.debug("Logged aviato sandbox %s to wandb", sandbox_id)
    except Exception as e:
        logger.warning("Failed to log aviato sandbox ID to wandb: %s", e)
