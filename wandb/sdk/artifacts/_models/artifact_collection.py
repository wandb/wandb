from __future__ import annotations

from typing import List, Optional

from pydantic import ConfigDict, Field
from typing_extensions import Annotated, Self

from wandb._pydantic import GQLId, Typename, field_validator
from wandb.sdk.artifacts._generated import ArtifactCollectionFragment
from wandb.sdk.artifacts._validators import (
    SOURCE_ARTIFACT_COLLECTION_TYPE,
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

    typename__: Typename[str]
    id: GQLId

    name: str
    type: str
    description: Optional[str] = None  # noqa: UP045
    created_at: Annotated[str, Field(frozen=True)]

    project: Annotated[str, Field(frozen=True)]
    entity: Annotated[str, Field(frozen=True)]

    aliases: Annotated[List[str], Field(default_factory=list, frozen=True)]  # noqa: UP006
    tags: Annotated[List[str], Field(default_factory=list)]  # noqa: UP006

    @field_validator("name")
    def _check_name(cls, v: str) -> str:
        return validate_artifact_name(v)

    @field_validator("tags")
    def _check_tags(cls, v: list[str]) -> list[str]:
        return validate_tags(v)

    @property
    def is_sequence(self) -> bool:
        """Returns True if the artifact collection is an ArtifactSequence (source collection)."""
        return self.typename__ == SOURCE_ARTIFACT_COLLECTION_TYPE

    @classmethod
    def from_fragment(cls, obj: ArtifactCollectionFragment) -> Self:
        if (project := obj.project) is None:
            raise ValueError(f"Missing 'project' in {type(obj)!r} data")

        # Extract just the alias/tag names
        aliases = (
            [node.alias for edge in conn.edges if (node := edge.node)]
            if (conn := obj.aliases)
            else []
        )
        tags = (
            [node.name for edge in conn.edges if (node := edge.node)]
            if (conn := obj.tags)
            else []
        )
        return cls(
            typename__=obj.typename__,
            id=obj.id,
            name=obj.name,
            type=obj.default_artifact_type.name,
            description=obj.description,
            created_at=obj.created_at,
            project=project.name,
            entity=project.entity_name,
            tags=tags,
            aliases=aliases,
        )
