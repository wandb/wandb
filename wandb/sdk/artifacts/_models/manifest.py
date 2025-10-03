# Older-style type annotations required for Pydantic v1 / python 3.8 compatibility.
# ruff: noqa: UP006

from __future__ import annotations

from typing import Any, Dict, Literal

from pydantic import Field

from wandb._pydantic import field_validator, to_camel

from ..artifact_manifest_entry import ArtifactManifestEntry
from .base_model import ArtifactsBase


class ArtifactManifestV1Data(ArtifactsBase, frozen=True, alias_generator=to_camel):
    """Data model for the v1 artifact manifest."""

    version: Literal[1]
    contents: Dict[str, ArtifactManifestEntry] = Field(default_factory=dict)
    storage_policy: str
    storage_policy_config: Dict[str, Any]

    @field_validator("contents", mode="before")
    def _validate_entries(cls, v: Any) -> Any:
        # The dict keys should be the `entry.path` values, but they've
        # historically been dropped from the JSON objects. This restores
        # them on instantiation.
        # Pydantic will handle converting dicts -> ArtifactManifestEntries.
        return {path: {**dict(entry), "path": path} for path, entry in v.items()}
