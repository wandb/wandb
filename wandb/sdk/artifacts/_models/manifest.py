from typing import Any, Dict, Literal

from wandb._pydantic import to_camel

from .base_model import ArtifactsBase


class ArtifactManifestV1Data(ArtifactsBase, frozen=True, alias_generator=to_camel):
    """Data model for the v1 artifact manifest."""

    version: Literal[1]

    contents: Dict[str, Dict[str, Any]]

    storage_policy: str
    storage_policy_config: Dict[str, Any]
