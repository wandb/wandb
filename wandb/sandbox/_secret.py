from __future__ import annotations

from dataclasses import dataclass

from cwsandbox import Secret as _BaseSecret

WANDB_SECRET_STORE = "wandb-team-secrets"


@dataclass(frozen=True, kw_only=True)
class Secret(_BaseSecret):
    """W&B sandbox secret with a default team secret store."""

    store: str = WANDB_SECRET_STORE
