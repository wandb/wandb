from __future__ import annotations

from typing import TYPE_CHECKING

from wandb import env

from .storage_layout import StorageLayout
from .storage_policies import WandbStoragePolicy

if TYPE_CHECKING:
    from .storage_policy import StoragePolicy


def make_storage_policy(storage_region: str | None = None) -> StoragePolicy:
    """A factory function that returns the default StoragePolicy for the current environment."""
    layout = StorageLayout.V1 if env.get_use_v1_artifacts() else StorageLayout.V2
    config = {"storageLayout": layout}
    # Only set storage region if is not None for backward compatibility
    # Validation such as non empty string is done in WandbStoragePolicy.__init__
    if storage_region is not None:
        config["storageRegion"] = storage_region
    return WandbStoragePolicy.from_config(config)
