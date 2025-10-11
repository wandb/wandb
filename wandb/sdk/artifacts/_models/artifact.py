from dataclasses import dataclass
from typing import Any, Literal, final

from pydantic import ConfigDict, Field, NonNegativeInt
from typing_extensions import Self

from wandb._pydantic import Frozen, GQLId, field_validator, model_validator
from wandb.sdk.artifacts._factories import make_storage_policy
from wandb.sdk.artifacts._generated import ArtifactFragment, MembershipWithArtifact
from wandb.sdk.artifacts._validators import (
    validate_artifact_name,
    validate_artifact_type,
    validate_metadata,
    validate_ttl_duration_seconds,
)
from wandb.sdk.artifacts.artifact_manifest import ArtifactManifest
from wandb.sdk.artifacts.artifact_manifests.artifact_manifest_v1 import (
    ArtifactManifestV1,
)
from wandb.sdk.artifacts.artifact_state import ArtifactState

from .base_model import ArtifactsBase


@final
@dataclass
class DeferredArtifactManifest:
    """A lightweight wrapper around the manifest URL, used to indicate deferred loading of the actual manifest."""

    url: str


class DraftArtifact(ArtifactsBase):
    base_id: GQLId
    id: None

    state: Literal[ArtifactState.PENDING] = ArtifactState.PENDING


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

    # client: RetryingClient | None = None

    # tmp_dir: tempfile.TemporaryDirectory | None = None

    # # TODO: Do we need these?  They're local i.e. don't require immediate API calls,
    # # but they're not really intrinsic properties of an Artifact.
    # added_objs: dict[int, tuple[WBValue, ArtifactManifestEntry]] = {}
    # added_local_paths: dict[str, ArtifactManifestEntry] = {}
    # save_handle: MailboxHandle[pb.Result] | None = None
    # download_roots: set[str] = set()

    # Set by new_draft(), otherwise the latest artifact will be used as the base.
    base_id: None = None  # TODO: should this only be defined on draft artifacts?

    id: GQLId

    # # TODO: Do we need these?
    # client_id: str = runid.generate_id(128)
    # sequence_client_id: str = runid.generate_id(128)

    # These may identify EITHER a linked or source artifact version
    entity: Frozen[str]
    project: Frozen[str]
    name: Frozen[str]  # includes version after saving
    version: Frozen[str]

    # These MUST identify the source artifact version.
    source_entity: Frozen[str]
    source_project: Frozen[str]
    source_name: Frozen[str]  # includes version after saving
    source_version: Frozen[str]

    # # TODO: Should we put this here, since it requires an API call?
    # source_artifact: Artifact | None = None

    # # TODO: This doesn't need to be a field, should be a computed property instead
    # is_link: bool = False

    # Intrinsic properties of the source artifact.
    type: Frozen[str]
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    ttl_duration_seconds: int | None = None
    ttl_is_inherited: bool = True
    # ttl_changed: bool = False  # TODO: I don't think we need this if we keep `saved` vs `current` instances

    aliases: list[str] = Field(default_factory=list)
    # saved_aliases: list[str] = []  # TODO: I don't think we need this if we keep `saved` vs `current` instances

    tags: list[str] = Field(default_factory=list)
    # saved_tags: list[str] = []  # TODO: I don't think we need this if we keep `saved` vs `current` instances

    # distributed_id: str | None = None  # TODO: What is this used for / do we need it here?

    # TODO: Verify, but we probably shouldn't treat this as a property of an Artifact
    #   In the backend, it seems to be set as ArtifactManifest.Type
    # incremental: bool = False

    state: ArtifactState
    manifest: ArtifactManifest | DeferredArtifactManifest | None = Field(
        default_factory=ArtifactManifestV1(storage_policy=make_storage_policy())
    )
    commit_hash: Frozen[str]
    file_count: Frozen[NonNegativeInt]
    created_at: Frozen[str]
    updated_at: Frozen[str]
    # final: bool = False  # TODO: Why do we even have this -- is it distinct from `state`?
    history_step: NonNegativeInt | None = None

    # # Note: we should consider making this lazy since it might involve API fetch calls
    # linked_artifacts: list[Artifact] = []

    @field_validator("name", "source_name", mode="before")
    def _validate_name(cls, v: Any) -> str:
        """Validate the artifact (collection) name."""
        return validate_artifact_name(v)

    @field_validator("version", "source_version", mode="before")
    def _validate_version(cls, v: Any) -> Any:
        """If given a valid integer version index, convert to a recognizable version string."""
        if isinstance(v, int):
            return f"v{v}"
        return v

    @field_validator("metadata", mode="before")
    def _validate_metadata(cls, v: Any) -> dict[str, Any]:
        return validate_metadata(v)

    @field_validator("ttl_duration_seconds", mode="before")
    def _validate_ttl_duration_seconds(cls, v: Any) -> int | None:
        return validate_ttl_duration_seconds(v)

    @field_validator("ttl_is_inherited", mode="before")
    def _validate_ttl_is_inherited(cls, v: Any) -> bool:
        """In case `ttl_is_inherited` is null or missing, default to `True`."""
        return True if (v is None) else v

    @model_validator(mode="after")
    def _forbid_reserved_type_and_name(self, v: Self) -> Self:
        # TODO: Only enforce this on non-internal artifacts
        return validate_artifact_type(self.type, self.name)

    @classmethod
    def from_source_fragment(cls, artifact: ArtifactFragment) -> Self:
        """Instantiate from a validated `ArtifactFragment`, presumably parsed from a GraphQL response.

        Note:
            For historical reasons, the `Artifact` GraphQL type represents the original ("source")
            artifact version, rather than e.g. a linked version within another `ArtifactCollection`.
        """
        if not (
            (src_collection := artifact.artifact_sequence)
            and (src_project := src_collection.project)
        ):
            raise ValueError("Parsed artifact fragment is missing source project")

        # Extract just the alias/tag names
        aliases = [a.alias for a in (artifact.aliases or [])]
        tags = [t.name for t in (artifact.tags or [])]

        return cls(
            id=artifact.id,
            entity=src_project.entity_name,
            project=src_project.name,
            name=src_collection.name,
            version=artifact.version_index,
            source_entity=src_project.entity_name,
            source_project=src_project.name,
            source_name=src_collection.name,
            source_version=artifact.version_index,
            type=artifact.artifact_type.name,
            description=artifact.description,
            metadata=artifact.metadata,
            ttl_duration_seconds=artifact.ttl_duration_seconds,
            ttl_is_inherited=artifact.ttl_is_inherited,
            aliases=aliases,
            tags=tags,
            state=artifact.state,
            manifest=(
                DeferredArtifactManifest(manifest.file.direct_url)
                if (manifest := artifact.current_manifest)
                else None
            ),
            commit_hash=artifact.commit_hash,
            file_count=artifact.file_count,
            created_at=artifact.created_at,
            updated_at=artifact.updated_at,
            history_step=artifact.history_step,
        )

    @classmethod
    def from_membership_fragment(cls, membership: MembershipWithArtifact) -> Self:
        """Instantiate from a validated `MembershipWithArtifact`, presumably parsed from a GraphQL response.

        Note:
            The `ArtifactMembership` GraphQL type can represent either of:
            - the original (logged) artifact version from its source `ArtifactCollection`
            - a linked version from another `ArtifactCollection`
        """
        if not (
            # Info about the collection for _this_ membership (linked or source)
            (collection := membership.artifact_collection)
            and (project := collection.project)
            # Info about the original (source) artifact
            and (artifact := membership.artifact)
            and (source_collection := artifact.artifact_sequence)
            and (source_project := source_collection.project)
        ):
            raise ValueError(
                "Parsed artifact membership fragment is missing source or linked project"
            )

        # Extract just the alias/tag names
        aliases = [a.alias for a in (artifact.aliases or [])]
        tags = [t.name for t in (artifact.tags or [])]
        return cls(
            id=artifact.id,
            entity=project.entity_name,
            project=project.name,
            name=collection.name,
            version=membership.version_index,
            source_entity=source_project.entity_name,
            source_project=source_project.name,
            source_name=source_collection.name,
            source_version=artifact.version_index,
            type=artifact.artifact_type.name,
            description=artifact.description,
            metadata=artifact.metadata,
            ttl_duration_seconds=artifact.ttl_duration_seconds,
            ttl_is_inherited=artifact.ttl_is_inherited,
            aliases=aliases,
            tags=tags,
            state=artifact.state,
            manifest=(
                DeferredArtifactManifest(manifest.file.direct_url)
                if (manifest := artifact.current_manifest)
                else None
            ),
            commit_hash=artifact.commit_hash,
            file_count=artifact.file_count,
            created_at=artifact.created_at,
            updated_at=artifact.updated_at,
            history_step=artifact.history_step,
        )
