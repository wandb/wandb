from __future__ import annotations

from wandb import env

from .storage_layout import StorageLayout
from .storage_policies import WANDB_STORAGE_POLICY
from .storage_policy import StoragePolicy


def make_storage_policy() -> StoragePolicy:
    """A factory function that returns the default StoragePolicy for the current environment."""
    policy_cls = StoragePolicy.lookup_by_name(WANDB_STORAGE_POLICY)
    layout = StorageLayout.V1 if env.get_use_v1_artifacts() else StorageLayout.V2
    return policy_cls.from_config({"storageLayout": layout})
