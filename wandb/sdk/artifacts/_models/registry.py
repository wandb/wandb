from __future__ import annotations

from typing import Any, Optional

from pydantic import ConfigDict, Field
from typing_extensions import Self

from wandb._pydantic import GQLId, field_validator
from wandb._strutils import nameof
from wandb.apis.public.registries._freezable_list import AddOnlyArtifactTypesList
from wandb.apis.public.registries._utils import Visibility
from wandb.sdk.artifacts._generated import RegistryFragment
from wandb.sdk.artifacts._generated.fragments import RegistryFragmentArtifactTypes
from wandb.sdk.artifacts._validators import REGISTRY_PREFIX, remove_registry_prefix

from .base_model import ArtifactsBase


class RegistryData(ArtifactsBase):
    """Transport-free model for local `Registry` data.

    For now, this is separated from the public `Registry` class
    to more easily ensure continuity in the public `Registry` API.
    """

    model_config = ConfigDict(
        str_min_length=1,  # Strings cannot be empty
    )

    id: GQLId = Field(frozen=True)
    """The unique, encoded ID for this registry."""

    created_at: str = Field(frozen=True)
    """When this registry was created."""

    updated_at: Optional[str] = Field(frozen=True)
    """When this registry was last updated."""

    organization: str = Field(frozen=True)
    """The organization of the registry."""

    entity: str = Field(frozen=True)
    """The organization entity of the registry."""

    name: str
    """The name of the registry without the `wandb-registry-` project prefix."""

    description: Optional[str] = None
    """The description, if any, of the registry."""

    allow_all_artifact_types: bool
    """Whether all artifact types are allowed in the registry."""

    artifact_types: AddOnlyArtifactTypesList = Field(
        default_factory=AddOnlyArtifactTypesList
    )
    """The artifact types allowed in the registry.

    The meaning of this list depends on the value of `allow_all_artifact_types`:
    - If True: `artifact_types` are the previously-saved or currently-used types in the registry.
    - If False: `artifact_types` are the only allowed artifact types in the registry.
    """

    visibility: Visibility = Field(alias="access")
    """The visibility of the registry."""

    @property
    def full_name(self) -> str:
        """The full project name of the registry, including the expected `wandb-registry-` prefix."""
        return f"{REGISTRY_PREFIX}{self.name}"

    @field_validator("artifact_types", mode="plain")
    def _validate_artifact_types(cls, v: Any) -> AddOnlyArtifactTypesList:
        """Coerce `artifact_types` to an AddOnlyArtifactTypesList."""
        if isinstance(v, RegistryFragmentArtifactTypes):
            # This is a GQL connection object, so we need to extract the node names
            return AddOnlyArtifactTypesList(e.node.name for e in v.edges if e.node)

        # By default, assume we were passed an iterable of strings
        return AddOnlyArtifactTypesList(v)

    @classmethod
    def from_fragment(cls, obj: RegistryFragment) -> Self:
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
