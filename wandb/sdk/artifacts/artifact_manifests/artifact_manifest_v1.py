"""Artifact manifest v1."""

# Keep older-style type annotations in this legacy model.
# ruff: noqa: UP006, UP035

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from operator import itemgetter
from typing import Annotated, Any, ClassVar, Dict, Literal, final

from pydantic import Field

from wandb.sdk.lib.hashutil import HexDigest, _md5, _xxh128, md5_file_b64

from .._factories import make_storage_policy
from .._generated import ArtifactDigestAlgorithm
from .._models.manifest import ArtifactManifestV1Data
from ..artifact_manifest import ArtifactManifest
from ..artifact_manifest_entry import DIGEST_ALGORITHM_EXTRA_KEY, ArtifactManifestEntry
from ..storage_policy import StoragePolicy


@final
class ArtifactManifestV1(ArtifactManifest):
    manifest_version: Annotated[Literal[1], Field(repr=False)] = 1
    entries: Dict[str, ArtifactManifestEntry] = Field(default_factory=dict)

    storage_policy: StoragePolicy = Field(
        default_factory=make_storage_policy, exclude=True, repr=False
    )

    digest_algorithm: Annotated[
        ArtifactDigestAlgorithm, Field(exclude=True, repr=False)
    ]

    @classmethod
    def from_manifest_json(
        cls,
        manifest_json: dict[str, Any],
        digest_algorithm: ArtifactDigestAlgorithm = ArtifactDigestAlgorithm.MANIFEST_MD5,
    ) -> ArtifactManifestV1:
        data = ArtifactManifestV1Data(**manifest_json)

        policy_name = data.storage_policy
        policy_cfg = data.storage_policy_config
        policy = StoragePolicy.lookup_by_name(policy_name).from_config(policy_cfg)
        return cls(
            manifest_version=data.version,
            entries=data.contents,
            storage_policy=policy,
            digest_algorithm=digest_algorithm,
        )

    def to_manifest_json(self) -> dict:
        """This is the JSON that's stored in wandb_manifest.json.

        If include_local is True we also include the local paths to files. This is
        used to represent an artifact that's waiting to be saved on the current
        system. We don't need to include the local paths in the artifact manifest
        contents.
        """
        omit_entry_fields = {"path", "local_path", "skip_cache"}
        return {
            "version": self.manifest_version,
            "storagePolicy": self.storage_policy.name(),
            "storagePolicyConfig": self.storage_policy.config(),
            "contents": {
                path: entry.model_dump(exclude=omit_entry_fields, exclude_defaults=True)
                for path, entry in self.entries.items()
            },
        }

    _DIGEST_HEADER: ClassVar[bytes] = b"wandb-artifact-manifest-v1\n"
    """Encoded prefix/header for the ArtifactManifest digest."""

    def digest(self) -> HexDigest:
        hasher = (
            _xxh128(self._DIGEST_HEADER)
            if self.digest_algorithm == ArtifactDigestAlgorithm.MANIFEST_XXH128
            else _md5(self._DIGEST_HEADER)
        )
        # sort by key (path)
        for path, entry in sorted(self.entries.items(), key=itemgetter(0)):
            hasher.update(f"{path}:{entry.digest}\n".encode())
        return hasher.hexdigest()

    def size(self) -> int:
        return sum(entry.size for entry in self.entries.values() if entry.size)

    def hash_contents_with_md5(self) -> None:
        """Re-hash all of the entries with MD5."""

        def _rehash(item: ArtifactManifestEntry) -> None:
            if (
                not item.local_path
                or item.digest_algorithm() is ArtifactDigestAlgorithm.MANIFEST_MD5
            ):
                return
            item.digest = md5_file_b64(item.local_path)
            del item.extra[DIGEST_ALGORITHM_EXTRA_KEY]

        with ThreadPoolExecutor(max_workers=16) as executor:
            futures = [executor.submit(_rehash, item) for item in self.entries.values()]
            for future in as_completed(futures):
                future.result()
