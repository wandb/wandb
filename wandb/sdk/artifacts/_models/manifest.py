from typing import Any, Literal, final

from pydantic import field_validator
from pydantic.alias_generators import to_camel

from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry

from .base_model import ArtifactsBase
from .storage import StoragePolicyConfig


@final
class ArtifactManifestV1Data(ArtifactsBase, alias_generator=to_camel):
    """Data model for the v1 artifact manifest."""

    version: Literal[1]

    contents: dict[str, ArtifactManifestEntry]

    storage_policy: str
    storage_policy_config: StoragePolicyConfig

    @field_validator("contents", mode="before")
    def _validate_entries(cls, v: Any) -> Any:
        # The dict keys should be the `entry.path` values, but they've
        # historically been dropped from the JSON objects. This restores
        # them on instantiation.
        # Pydantic will handle converting dicts -> ArtifactManifestEntries.
        return {path: {**dict(entry), "path": path} for path, entry in v.items()}
