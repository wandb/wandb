from __future__ import annotations

from abc import ABC
from typing import Any, Literal, Optional

from pydantic import Field, NonNegativeInt
from typing_extensions import Self

from wandb._pydantic import GQLId, field_validator, model_validator

from .._generated import ArtifactFragment
from .._validators import (
    ArtifactPath,
    FullArtifactPath,
    validate_artifact_name,
    validate_metadata,
    validate_project_name,
    validate_ttl_duration_seconds,
)
from ..artifact_manifests.artifact_manifest_v1 import ArtifactManifestV1
from ..artifact_state import ArtifactState
from .base_model import ArtifactsBase


class BaseArtifactData(ArtifactsBase, ABC):
    """Base class for all artifact data models."""

    state: Any

    base_id: Any
    id: Any

    type: str = Field(min_length=1)
    description: Optional[str] = None

    # These may identify EITHER a linked or source artifact version
    path: ArtifactPath
    version: Any

    # These MUST identify the source artifact version.
    source_path: ArtifactPath
    source_version: Any

    metadata: dict[str, Any] = Field(default_factory=dict)

    ttl_duration_seconds: Optional[int] = None
    ttl_is_inherited: bool = True

    aliases: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    size: Any = None
    digest: Any = None
    manifest: Any = None
    commit_hash: Any = None
    file_count: Any = None

    created_at: Any = None
    updated_at: Any = None

    history_step: Any = None

    @field_validator("metadata", mode="plain")
    def _validate_metadata(cls, v: Any) -> dict[str, Any]:
        return validate_metadata(v)

    @model_validator(mode="before")
    @classmethod
    def _default_to_source_path(cls, v: Any) -> Any:
        if (source_path := v.get("source_path")) is not None:
            v.setdefault("path", source_path)
        if (source_version := v.get("source_version")) is not None:
            v.setdefault("version", source_version)
        return v


class DraftArtifactData(BaseArtifactData):
    """A local instance of `Artifact` data that hasn't been logged (i.e. saved) yet."""

    state: Literal[ArtifactState.PENDING] = ArtifactState.PENDING

    base_id: Optional[GQLId] = None

    # Draft artifacts don't have an ID until they're logged.
    id: Any = None

    type: str = Field(min_length=1)
    description: Optional[str] = None


class ArtifactData(BaseArtifactData):
    """Transport-free model for a local instance of saved `Artifact` data.

    For now, this is separated from the public `Artifact` model
    to more easily ensure continuity in the public `Artifact` API.

    Note:
        In a future change, consider making _this_ the public `Artifact` instead, i.e.:
        - Replace the _existing_ `Artifact` class with this one
        - Rename _this_ class to `Artifact`
        Note that this would be a breaking change.
    """

    state: ArtifactState

    base_id: None = None  # TODO: should this only be defined at all on draft artifacts?
    """Set by new_draft(), otherwise the latest artifact will be used as the base."""

    id: GQLId

    # These may identify EITHER a linked or source artifact version
    path: FullArtifactPath
    version: str

    # These MUST identify the source artifact version.
    source_path: FullArtifactPath
    source_version: str

    # Intrinsic properties of the source artifact.
    type: str
    description: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    ttl_duration_seconds: int | None = None
    ttl_is_inherited: bool = True

    aliases: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    # TODO: What is this used for / do we need it here?
    # distributed_id: str | None = None

    # TODO: Verify, but we probably shouldn't treat this as a property of an Artifact
    #   In the backend, it seems to be set as ArtifactManifest.Type
    # incremental: bool = False

    # NOTE: These fields only reflect the last fetched response from the
    # server, if any. If the ArtifactManifest has already been fetched and/or
    # populated locally, it should take priority when determining these values.
    size: Optional[NonNegativeInt] = None
    digest: Optional[str] = None

    manifest: Optional[ArtifactManifestV1] = None

    commit_hash: str
    file_count: NonNegativeInt

    created_at: str
    updated_at: Optional[str]

    # final: bool = False  # TODO: Why do we even have this? Is it distinct from `state`?

    history_step: NonNegativeInt | None = None

    @model_validator(mode="before")
    @classmethod
    def _default_to_source_path(cls, v: Any) -> Any:
        if (source_path := v.get("source_path")) is not None:
            v.setdefault("path", source_path)
        if (source_version := v.get("source_version")) is not None:
            v.setdefault("version", source_version)
        return v

    @field_validator("source_version", "version", mode="plain")
    def _validate_version(cls, v: Any) -> Any:
        """If given an integer version index, convert it to a version string."""
        return f"v{v}" if isinstance(v, int) else v

    @field_validator("ttl_duration_seconds", mode="plain")
    def _validate_ttl_duration_seconds(cls, v: Any) -> int | None:
        return validate_ttl_duration_seconds(v)

    @field_validator("ttl_is_inherited", mode="plain")
    def _validate_ttl_is_inherited(cls, v: Any) -> bool:
        """In case `ttl_is_inherited` is null or missing, default to `True`."""
        return True if (v is None) else v

    @model_validator(mode="after")
    def _validate_paths(self) -> Self:
        """Validate the artifact paths after they've been set."""
        validate_artifact_name(self.source_path.name.split(":")[0])
        validate_artifact_name(self.path.name.split(":")[0])
        validate_project_name(self.source_path.project)
        validate_project_name(self.path.project)
        return self

    # @model_validator(mode="after")
    # def _forbid_reserved_type_and_name(self) -> Self:
    #     # TODO: Only enforce this on non-internal artifacts
    #     validate_artifact_type(self.type, self.path.name.split(":")[0])
    #     return self

    @classmethod
    def from_artifact_fragment(cls, obj: ArtifactFragment, **kwargs: Any) -> Self:
        """Instantiate from an `ArtifactFragment`, likely from a GQL response.

        Note:
            For historical reasons, the `Artifact` GraphQL type represents the
            original ("source") artifact version, rather than e.g. a linked version
            within another `ArtifactCollection`.
        """
        return cls(
            id=obj.id,
            source_path=FullArtifactPath.from_collection_fragment(
                obj.artifact_sequence
            ),
            source_version=obj.version_index,
            type=obj.artifact_type.name,
            description=obj.description,
            metadata=obj.metadata,
            ttl_duration_seconds=obj.ttl_duration_seconds,
            ttl_is_inherited=obj.ttl_is_inherited,
            aliases=[a.alias for a in (obj.aliases or [])],
            tags=[t.name for t in (obj.tags or [])],
            state=obj.state,
            manifest=None,
            commit_hash=obj.commit_hash,
            file_count=obj.file_count,
            created_at=obj.created_at,
            updated_at=obj.updated_at,
            history_step=obj.history_step,
            **kwargs,
        )


DraftArtifactData.model_rebuild()
ArtifactData.model_rebuild()
