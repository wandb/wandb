"""S3 bucket storage policy."""
from typing import TYPE_CHECKING, Dict, Optional, Sequence, Union

from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry
from wandb.sdk.artifacts.storage_handlers.local_file_handler import LocalFileHandler
from wandb.sdk.artifacts.storage_handlers.multi_handler import MultiHandler
from wandb.sdk.artifacts.storage_handlers.s3_handler import S3Handler
from wandb.sdk.artifacts.storage_handlers.tracking_handler import TrackingHandler
from wandb.sdk.artifacts.storage_policy import StoragePolicy

if TYPE_CHECKING:
    from wandb.sdk.artifacts.artifact import Artifact
    from wandb.sdk.lib.paths import FilePathStr, URIStr


# Don't use this yet!
class __S3BucketPolicy(StoragePolicy):  # noqa: N801
    @classmethod
    def name(cls) -> str:
        return "wandb-s3-bucket-policy-v1"

    @classmethod
    def from_config(cls, config: Dict[str, str]) -> "__S3BucketPolicy":
        if "bucket" not in config:
            raise ValueError("Bucket name not found in config")
        return cls(config["bucket"])

    def __init__(self, bucket: str) -> None:
        self._bucket = bucket
        s3 = S3Handler(bucket)
        local = LocalFileHandler()

        self._handler = MultiHandler(
            handlers=[
                s3,
                local,
            ],
            default_handler=TrackingHandler(),
        )

    def config(self) -> Dict[str, str]:
        return {"bucket": self._bucket}

    def load_path(
        self,
        manifest_entry: ArtifactManifestEntry,
        local: bool = False,
    ) -> Union[URIStr, FilePathStr]:
        return self._handler.load_path(manifest_entry, local=local)

    def store_path(
        self,
        artifact: "Artifact",
        path: Union[URIStr, FilePathStr],
        name: Optional[str] = None,
        checksum: bool = True,
        max_objects: Optional[int] = None,
    ) -> Sequence[ArtifactManifestEntry]:
        return self._handler.store_path(
            artifact, path, name=name, checksum=checksum, max_objects=max_objects
        )
