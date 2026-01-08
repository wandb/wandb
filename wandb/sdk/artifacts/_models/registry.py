from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import Field, field_validator
from typing_extensions import Self

from wandb._pydantic import GQLId
from wandb._strutils import nameof
from wandb.apis.public.registries._freezable_list import AddOnlyArtifactTypesList
from wandb.apis.public.registries._utils import Visibility

from .base_model import ArtifactsBase

if TYPE_CHECKING:
    from wandb.sdk.artifacts._generated import RegistryFragment


class RegistryData(ArtifactsBase):
    """Transport-free model for local `Registry` data.

    For now, this is separated from the public `Registry` class
    to more easily ensure continuity in the public `Registry` API.
    """

    id: GQLId = Field(frozen=True)
    """The unique, encoded ID for this registry."""

    created_at: str = Field(frozen=True)
    """When this registry was created."""

    updated_at: str | None = Field(frozen=True)
    """When this registry was last updated."""

    organization: str = Field(frozen=True)
    """The organization of the registry."""

    entity: str = Field(frozen=True)
    """The organization entity of the registry."""

    name: str = Field(min_length=1)  # Disallow empty strings
    """The name of the registry without the `wandb-registry-` project prefix."""

    description: str | None = None
    """The description, if any, of the registry."""

    allow_all_artifact_types: bool
    """Whether all artifact types are allowed in the registry."""

    artifact_types: AddOnlyArtifactTypesList = Field(
        default_factory=AddOnlyArtifactTypesList
    )
    """The artifact types allowed in the registry.

    The meaning of this list depends on `allow_all_artifact_types`:
    - If True: `artifact_types` are the previously saved or currently used
      types in the registry.
    - If False: `artifact_types` are the only allowed artifact types in the
      registry.
    """

    visibility: Visibility = Field(alias="access")
    """The visibility of the registry."""

    @property
    def full_name(self) -> str:
        """The project name with the expected `wandb-registry-` prefix."""
        from wandb.sdk.artifacts._validators import REGISTRY_PREFIX

        return f"{REGISTRY_PREFIX}{self.name}"

    @field_validator("artifact_types", mode="plain")
    def _validate_artifact_types(cls, v: Any) -> AddOnlyArtifactTypesList:
        """Coerce `artifact_types` to an AddOnlyArtifactTypesList."""
        from wandb.sdk.artifacts._generated.fragments import (
            RegistryFragmentArtifactTypes,
        )

        if isinstance(v, RegistryFragmentArtifactTypes):
            # This is a GQL connection object, so we need to extract the node names
            return AddOnlyArtifactTypesList(e.node.name for e in v.edges if e.node)

        # By default, assume we were passed an iterable of strings
        return AddOnlyArtifactTypesList(v)

    @classmethod
    def from_fragment(cls, obj: RegistryFragment) -> Self:
        from wandb.sdk.artifacts._validators import remove_registry_prefix

        if not obj.entity.organization:
            raise ValueError(
                f"Unable to parse registry organization from {nameof(type(obj))!r} object"
            )

        return cls(
            id=obj.id,
            created_at=obj.created_at,
            updated_at=obj.updated_at,
            organization=obj.entity.organization.name,
            entity=obj.entity.name,
            name=remove_registry_prefix(obj.name),
            description=obj.description,
            allow_all_artifact_types=obj.allow_all_artifact_types,
            artifact_types=obj.artifact_types,
            visibility=obj.access,
        )
