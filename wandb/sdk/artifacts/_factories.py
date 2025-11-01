from __future__ import annotations

from typing import TYPE_CHECKING

from ._models.storage import StoragePolicyConfig
from .storage_policies import WandbStoragePolicy

if TYPE_CHECKING:
    from .storage_policy import StoragePolicy


def make_storage_policy(region: str | None = None) -> StoragePolicy:
    """Returns the default `StoragePolicy` for the current environment."""
    return WandbStoragePolicy(config=StoragePolicyConfig.from_env(region=region))
