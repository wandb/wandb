from __future__ import annotations

from typing import TYPE_CHECKING

from wandb import env
from wandb.util import get_artifact_storage_region

from .storage_layout import StorageLayout
from .storage_policies import WandbStoragePolicy

if TYPE_CHECKING:
    from .storage_policy import StoragePolicy


def make_storage_policy() -> StoragePolicy:
    """A factory function that returns the default StoragePolicy for the current environment."""
    layout = StorageLayout.V1 if env.get_use_v1_artifacts() else StorageLayout.V2
    config = {"storageLayout": layout}
    if get_artifact_storage_region() == "coreweave-us":
        config["storageRegion"] = "coreweave-us"
    return WandbStoragePolicy.from_config(config)
