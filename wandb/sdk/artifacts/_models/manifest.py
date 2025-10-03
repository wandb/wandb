# Older-style type annotations required for Pydantic v1 / python 3.8 compatibility.
# ruff: noqa: UP006

from __future__ import annotations

from operator import itemgetter
from typing import Any, Dict, Literal, Union

from pydantic import Field, TypeAdapter
from typing_extensions import Annotated

from wandb._pydantic import field_validator, to_camel
from wandb.sdk.lib.hashutil import HexMD5, _md5

from ..artifact_manifest_entry import ArtifactManifestEntry
from .base_model import ArtifactsBase


class DummyManifestData(ArtifactsBase, alias_generator=to_camel):
    """Data model for a placeholder artifact manifest.

    This should never be instantiated directly.  It's only used as a base case for the ManifestData union.
    """

    version: Literal[None] = None


class V1ManifestData(ArtifactsBase, alias_generator=to_camel):
    """Data model for the v1 artifact manifest."""

    version: Literal[1] = 1

    storage_policy: str
    storage_policy_config: Dict[str, Any]

    contents: Dict[str, ArtifactManifestEntry] = Field(default_factory=dict)

    @field_validator("contents", mode="before")
    def _validate_entries(cls, v: Any) -> Any:
        # The dict keys should be the `entry.path` values, but they've
        # historically been dropped from the JSON objects. This restores
        # them on instantiation.
        # Pydantic will handle converting dicts -> ArtifactManifestEntries.
        return {path: {**dict(entry), "path": path} for path, entry in v.items()}

    def digest(self) -> HexMD5:
        hasher = _md5()
        hasher.update(b"wandb-artifact-manifest-v1\n")
        # sort by key (path)
        for name, entry in sorted(self.contents.items(), key=itemgetter(0)):
            hasher.update(f"{name}:{entry.digest}\n".encode())
        return HexMD5(hasher.hexdigest())


ManifestData = Annotated[
    Union[DummyManifestData, V1ManifestData],
    Field(discriminator="version"),
]

ManifestDataAdapter = TypeAdapter(ManifestData)
