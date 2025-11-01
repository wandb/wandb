"""Storage layout."""

from __future__ import annotations

from enum import Enum


class StorageLayout(str, Enum):
    V1 = "V1"
    V2 = "V2"

    @classmethod
    def from_env(cls) -> StorageLayout:
        from wandb.env import get_use_v1_artifacts

        return cls.V1 if get_use_v1_artifacts() else cls.V2
