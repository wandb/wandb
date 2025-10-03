from __future__ import annotations

from typing import Optional

from pydantic import ConfigDict

from wandb._pydantic import to_camel

from .base_model import ArtifactsBase


class WandbStoragePolicyConfig(ArtifactsBase):
    model_config = ConfigDict(
        alias_generator=to_camel,
        str_min_length=1,
        str_strip_whitespace=True,
    )

    storage_layout: Optional[str] = None  # noqa: UP045
    storage_region: Optional[str] = None  # noqa: UP045
