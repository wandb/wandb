"""Artifact manifest."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from pydantic import Field
from typing_extensions import Self

from wandb._pydantic import model_validator
from wandb.sdk.artifacts._factories import make_storage_policy
from wandb.sdk.internal.internal_api import Api as InternalApi
from wandb.sdk.lib.hashutil import HexMD5

from ._models.base_model import ArtifactsBase
from ._models.manifest import ManifestData, ManifestDataAdapter, V1ManifestData
from .storage_policy import StoragePolicy

if TYPE_CHECKING:
    from .artifact_manifest_entry import ArtifactManifestEntry


#: Inner ArtifactManifestEntry fields to keep when dumping the ArtifactManifest to JSON.
_JSONABLE_MANIFEST_ENTRY_FIELDS: Final[frozenset[str]] = frozenset(
    ("digest", "birth_artifact_id", "ref", "extra", "size")
)


class ArtifactManifest(ArtifactsBase):
    # # Note: this can't be named "version" since it conflicts with the prior `version()` classmethod.
    # manifest_version: Annotated[int, Field(alias="version", repr=False)]
    # entries: Dict[str, ArtifactManifestEntry] = Field(default_factory=dict)

    # storage_policy: StoragePolicy = Field(exclude=True, repr=False)

    data: ManifestData
    storage_policy: StoragePolicy = Field(default_factory=make_storage_policy)

    @model_validator(mode="after")
    def _set_manifest_data(self) -> Self:
        self.data.storage_policy = self.storage_policy.name()
        self.data.storage_policy_config = self.storage_policy.config()
        return self

    # @classmethod
    # def version(cls) -> int:
    #     return cls.model_fields["manifest_version"].default

    def version(self) -> int:
        # return self.manifest_version
        return self.data.version

    @property
    def entries(self) -> dict[str, ArtifactManifestEntry]:
        return self.data.contents

    # @property
    # def storage_policy(self) -> StoragePolicy:
    #     return self._storage_policy

    @classmethod
    # @abstractmethod
    def from_manifest_json(
        cls, manifest_json: dict[str, Any], api: InternalApi | None = None
    ) -> Self:
        data = ManifestDataAdapter.validate_python(manifest_json)
        storage_policy = StoragePolicy.lookup_by_name(data.storage_policy).from_config(
            data.storage_policy_config, api=api
        )
        return cls(data=data, storage_policy=storage_policy)

        # if (version := manifest_json.get("version")) is None:
        #     raise ValueError("Invalid manifest format. Must contain version field.")

        # for sub in cls.__subclasses__():
        #     if sub.version() == version:
        #         return sub.from_manifest_json(manifest_json, api=api)
        # raise ValueError("Invalid manifest version.")

    @classmethod
    def from_storage_policy(cls, storage_policy: StoragePolicy) -> Self:
        """Create a new artifact manifest from a StoragePolicy instance."""
        return cls(
            data=V1ManifestData(
                storage_policy=storage_policy.name(),
                storage_policy_config=storage_policy.config(),
            ),
            storage_policy=storage_policy,
        )

    def __len__(self) -> int:
        return len(self.entries)

    # @abstractmethod
    def to_manifest_json(self) -> dict[str, Any]:
        """This is the JSON that's stored in wandb_manifest.json.

        If include_local is True we also include the local paths to files. This is
        used to represent an artifact that's waiting to be saved on the current
        system. We don't need to include the local paths in the artifact manifest
        contents.
        """
        kept_entry_fields = set(_JSONABLE_MANIFEST_ENTRY_FIELDS)
        return {
            # "version": self.manifest_version,
            "version": self.data.version,
            "storagePolicy": self.storage_policy.name(),
            "storagePolicyConfig": self.storage_policy.config(),
            "contents": {
                path: entry.model_dump(include=kept_entry_fields, exclude_defaults=True)
                for path, entry in self.entries.items()
            },
        }
        # raise NotImplementedError

    # @abstractmethod
    def digest(self) -> HexMD5:
        return self.data.digest()

        # hasher = _md5()
        # hasher.update(b"wandb-artifact-manifest-v1\n")
        # # sort by key (path)
        # for name, entry in sorted(self.entries.items(), key=itemgetter(0)):
        #     hasher.update(f"{name}:{entry.digest}\n".encode())
        # return HexMD5(hasher.hexdigest())
        # raise NotImplementedError

    def add_entry(self, entry: ArtifactManifestEntry, overwrite: bool = False) -> None:
        if (
            (not overwrite)
            and (old_entry := self.entries.get(entry.path))
            and (entry.digest != old_entry.digest)
        ):
            raise ValueError(f"Cannot add the same path twice: {entry.path!r}")
        self.entries[entry.path] = entry

    def remove_entry(self, entry: ArtifactManifestEntry) -> None:
        try:
            del self.entries[entry.path]
        except LookupError:
            raise FileNotFoundError(f"Cannot remove missing entry: {entry.path!r}")

    def get_entry_by_path(self, path: str) -> ArtifactManifestEntry | None:
        return self.entries.get(path)

    def get_entries_in_directory(self, directory: str) -> list[ArtifactManifestEntry]:
        # entry keys (paths) use forward slash even for windows
        dir_prefix = f"{directory}/"
        return [obj for key, obj in self.entries.items() if key.startswith(dir_prefix)]
