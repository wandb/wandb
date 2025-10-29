from __future__ import annotations

from typing import Any, List, Optional, Tuple

from pydantic import ConfigDict, Field
from typing_extensions import Self

from wandb._pydantic import field_validator
from wandb.sdk.artifacts._generated import ArtifactCollectionFragment
from wandb.sdk.artifacts._validators import (
    SOURCE_COLLECTION_TYPENAME,
    validate_artifact_name,
    validate_tags,
)

from .base_model import ArtifactsBase


class ArtifactCollectionData(ArtifactsBase):
    """Transport-free model for local `ArtifactCollection` data.

    For now, this is separated from the public `ArtifactCollection` model
    to more easily ensure continuity in the public `ArtifactCollection` API.

    Note:
        In a future change, consider making _this_ the public `ArtifactCollection` instead, i.e.:
        - Replace the _existing_ `ArtifactCollection` class with this one
        - Rename _this_ class to `ArtifactCollection`
        Note that this would be a breaking change.
    """

    model_config = ConfigDict(
        str_min_length=1,  # Strings cannot be empty
    )

    typename__: str = Field(alias="__typename", frozen=True, repr=False)
    """The GraphQL `__typename` for this object."""

    id: str = Field(frozen=True, repr=False)
    """The encoded GraphQL ID for this object."""

    name: str
    """The name of this collection."""

    type: str
    """The artifact type of this collection."""

    description: Optional[str] = None
    """The description, if any, for this collection."""

    created_at: str = Field(frozen=True)
    """When this collection was created."""

    project: str = Field(frozen=True)
    """The name of this collection's project."""

    entity: str = Field(frozen=True)
    """The name of the entity that owns this collection's project."""

    aliases: Optional[Tuple[str, ...]] = Field(default=None, frozen=True)
    """All aliases assigned to artifact versions within this collection.

    Note:
        `None` should signal that aliases haven't been (or couldn't be) fetched and parsed yet,
        for any reason, NOT the actual absence of aliases in this collection.
    """

    tags: List[str] = Field(default_factory=list)
    """The tags assigned to this collection.

    Note that this is distinct from any tags assigned to individual artifact versions within this collection.
    """

    @field_validator("name", mode="plain")
    def _validate_name(cls, v: str) -> str:
        return validate_artifact_name(v)

    @field_validator("tags", mode="plain")
    def _validate_tags(cls, v: Any) -> list[str]:
        """Ensure tags is a validated, deduped list of (str) tag names."""
        return validate_tags(v)

    @property
    def is_sequence(self) -> bool:
        """Returns True if the artifact collection is an ArtifactSequence (source collection)."""
        return self.typename__ == SOURCE_COLLECTION_TYPENAME

    @classmethod
    def from_fragment(cls, obj: ArtifactCollectionFragment) -> Self:
        """Instantiate this type from a GraphQL fragment."""
        if obj.project is None:
            raise ValueError(f"Missing project info in {type(obj)!r} data")

        return cls(
            typename__=obj.typename__,
            id=obj.id,
            name=obj.name,
            type=obj.type.name,
            description=obj.description,
            created_at=obj.created_at,
            project=obj.project.name,
            entity=obj.project.entity.name,
            tags=[e.node.name for e in obj.tags.edges if e.node],
            aliases=(
                [e.node.alias for e in obj.aliases.edges if e.node]
                if obj.aliases
                else []
            ),
        )
