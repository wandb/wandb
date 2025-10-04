from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import ConfigDict, Field, NonNegativeInt
from typing_extensions import Self

from wandb._pydantic import GQLId, field_validator, model_validator
from wandb.sdk.artifacts._generated import ArtifactFragment, ArtifactMembershipFragment
from wandb.sdk.artifacts._validators import (
    FullArtifactPath,
    validate_artifact_name,
    validate_artifact_type,
    validate_metadata,
    validate_project_name,
    validate_ttl_duration_seconds,
)
from wandb.sdk.artifacts.artifact_manifest import ArtifactManifest
from wandb.sdk.artifacts.artifact_state import ArtifactState

from .base_model import ArtifactsBase


class DraftArtifactData(ArtifactsBase):
    """A local instance of `Artifact` data that hasn't been logged (i.e. saved) yet."""

    state: Literal[ArtifactState.PENDING] = ArtifactState.PENDING

    base_id: GQLId

    # Draft artifacts don't have an ID until they're logged.
    id: None = Field(default=None, frozen=True)


class ArtifactData(ArtifactsBase):
    """Transport-free model for a local instance of saved `Artifact` data.

    For now, this is separated from the public `Artifact` model
    to more easily ensure continuity in the public `Artifact` API.

    Note:
        In a future change, consider making _this_ the public `Artifact` instead, i.e.:
        - Replace the _existing_ `Artifact` class with this one
        - Rename _this_ class to `Artifact`
        Note that this would be a breaking change.
    """

    model_config = ConfigDict(
        str_min_length=1,  # Strings cannot be empty
    )

    # # TODO: Do we need these?  They're local i.e. don't require immediate API calls,
    # # but they're not really intrinsic properties of an Artifact.
    # added_objs: dict[int, tuple[WBValue, ArtifactManifestEntry]] = {}
    # added_local_paths: dict[str, ArtifactManifestEntry] = {}
    # save_handle: MailboxHandle[pb.Result] | None = None
    # download_roots: set[str] = set()

    # Set by new_draft(), otherwise the latest artifact will be used as the base.
    base_id: None = None  # TODO: should this only be defined on draft artifacts?

    id: GQLId = Field(frozen=True)

    # These MUST identify the source artifact version.
    source_path: FullArtifactPath = Field(frozen=True)
    source_version: str = Field(frozen=True)

    # These may identify EITHER a linked or source artifact version
    path: FullArtifactPath = Field(frozen=True)
    version: str = Field(frozen=True)

    # Intrinsic properties of the source artifact.
    type: str = Field(frozen=True)
    description: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    ttl_duration_seconds: int | None = None
    ttl_is_inherited: bool = True

    aliases: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    # distributed_id: str | None = None  # TODO: What is this used for / do we need it here?

    # TODO: Verify, but we probably shouldn't treat this as a property of an Artifact
    #   In the backend, it seems to be set as ArtifactManifest.Type
    # incremental: bool = False

    state: ArtifactState

    manifest: ArtifactManifest | None = None
    commit_hash: str = Field(frozen=True)
    file_count: NonNegativeInt = Field(frozen=True)

    created_at: str = Field(frozen=True)
    updated_at: str = Field(frozen=True)

    # final: bool = False  # TODO: Why do we even have this -- is it distinct from `state`?

    history_step: NonNegativeInt | None = None

    # # Note: we should consider making this lazy since it might involve API fetch calls
    # linked_artifacts: list[Artifact] = []

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
        """If given a valid integer version index, convert to a recognizable version string."""
        return f"v{v}" if isinstance(v, int) else v

    @field_validator("metadata", mode="plain")
    def _validate_metadata(cls, v: Any) -> dict[str, Any]:
        return validate_metadata(v)

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

    @model_validator(mode="after")
    def _forbid_reserved_type_and_name(self) -> Self:
        # TODO: Only enforce this on non-internal artifacts
        validate_artifact_type(self.type, self.name)
        return self

    @classmethod
    def from_artifact_fragment(cls, obj: ArtifactFragment, **kwargs: Any) -> Self:
        """Instantiate from a validated `ArtifactFragment`, presumably parsed from a GraphQL response.

        Note:
            For historical reasons, the `Artifact` GraphQL type represents the original ("source")
            artifact version, rather than e.g. a linked version within another `ArtifactCollection`.
        """
        return cls(
            id=obj.id,
            source_path=FullArtifactPath.from_artifact_fragment(obj),
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

    @classmethod
    def from_membership_fragment(cls, obj: ArtifactMembershipFragment) -> Self:
        """Instantiate from a validated `ArtifactMembershipFragment`, presumably parsed from a GraphQL response.

        Note:
            The `ArtifactMembership` GraphQL type can represent either of:
            - the original (logged) artifact version from its source `ArtifactCollection`
            - a linked version from another `ArtifactCollection`
        """
        if not obj.artifact:
            raise ValueError("Artifact membership fragment is missing source artifact")
        return cls.from_artifact_fragment(
            obj.artifact,
            path=FullArtifactPath.from_membership_fragment(obj),
            version=obj.version_index,
        )
