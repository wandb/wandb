"""Sandbox wrapper with wandb integration.

- Auth
- Entity and Project from active wandb run, e.g. wandb.init(entity="foo", project="bar")
"""

from __future__ import annotations

from typing import Any

from cwsandbox import Sandbox as CWSandboxSandbox
from cwsandbox._defaults import SandboxDefaults

from ._auth import SandboxAuthContext, resolve_auth_context


class Sandbox(CWSandboxSandbox):
    """W&B-aware wrapper around `cwsandbox.Sandbox`."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._wandb_auth_context: SandboxAuthContext | None = None

    @classmethod
    def session(
        cls,
        defaults: SandboxDefaults | None = None,
    ):
        from ._session import Session

        return Session(defaults)

    @classmethod
    def _resolve_auth_metadata_cls(cls) -> tuple[tuple[str, str], ...]:
        return resolve_auth_context().metadata

    def _resolve_auth_metadata(self) -> tuple[tuple[str, str], ...]:
        if self._auth_metadata:
            return self._auth_metadata

        context = getattr(self, "_wandb_auth_context", None)
        if context is None:
            context = resolve_auth_context()
            self._wandb_auth_context = context
        return context.metadata
