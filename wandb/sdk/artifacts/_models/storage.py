from __future__ import annotations

from typing import Optional

from pydantic import ConfigDict, StrictStr
from typing_extensions import Self

from wandb._pydantic import to_camel
from wandb.sdk.artifacts.storage_layout import StorageLayout

from .base_model import ArtifactsBase


class StoragePolicyConfig(ArtifactsBase):
    model_config = ConfigDict(
        frozen=True,
        alias_generator=to_camel,
        str_min_length=1,
        str_strip_whitespace=True,
    )

    storage_layout: Optional[StorageLayout] = None
    storage_region: Optional[StrictStr] = None

    @classmethod
    def from_env(
        cls, layout: StorageLayout | None = None, region: str | None = None
    ) -> Self:
        """Instantiate with default values magically configured from the environment."""
        return cls(
            storage_layout=layout or StorageLayout.from_env(), storage_region=region
        )
