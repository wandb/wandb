from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Optional, Tuple

from pydantic import ConfigDict, Field
from typing_extensions import Self

from wandb._pydantic import field_validator

from .base_model import ArtifactsBase

if TYPE_CHECKING:
    from wandb.sdk.artifacts._generated import ArtifactCollectionFragment


class ArtifactCollectionData(ArtifactsBase):
    """Transport-free model for local `ArtifactCollection` data.

    For now, this is separated from the public `ArtifactCollection` model
    to more easily ensure continuity in the public `ArtifactCollection` API.

    Note:
        In a future change, consider making this the public `ArtifactCollection` class:
        - Replace the existing `ArtifactCollection` class with this one.
        - Rename this class to `ArtifactCollection`.
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
        `None` indicates that aliases have not been fetched or parsed yet for
        any reason, NOT that aliases are absent in this collection.
    """

    tags: List[str] = Field(default_factory=list)
    """The tags assigned to this collection.

    Note that this is distinct from tags assigned to individual artifact
    versions within the collection.
    """

    @field_validator("name", mode="plain")
    def _validate_name(cls, v: str) -> str:
        from wandb.sdk.artifacts._validators import validate_artifact_name

        return validate_artifact_name(v)

    @field_validator("tags", mode="plain")
    def _validate_tags(cls, v: Any) -> list[str]:
        """Ensure tags is a validated, deduped list of (str) tag names."""
        from wandb.sdk.artifacts._validators import validate_tags

        return validate_tags(v)

    @property
    def is_sequence(self) -> bool:
        """Return True if this collection is an `ArtifactSequence` (source collection)."""
        from wandb._pydantic import gql_typename
        from wandb.sdk.artifacts._generated import ArtifactSequenceTypeFields

        return self.typename__ == gql_typename(ArtifactSequenceTypeFields)

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
