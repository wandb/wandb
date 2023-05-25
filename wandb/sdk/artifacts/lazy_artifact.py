"""Lazy artifact."""
from typing import TYPE_CHECKING, Any, List, Optional, Union

from wandb.apis import PublicApi
from wandb.sdk.artifacts.artifact import Artifact as ArtifactInterface
from wandb.sdk.artifacts.exceptions import WaitTimeoutError
from wandb.sdk.artifacts.invalid_artifact import InvalidArtifact
from wandb.sdk.artifacts.public_artifact import Artifact as PublicArtifact
from wandb.sdk.lib.paths import FilePathStr, StrPath

if TYPE_CHECKING:
    import wandb.apis.public
    from wandb.data_types import WBValue
    from wandb.sdk.artifacts.artifact_manifest import ArtifactManifest
    from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry


class LazyArtifact(ArtifactInterface):
    _api: PublicApi
    _instance: Union[ArtifactInterface, InvalidArtifact]
    _future: Any

    def __init__(self, api: PublicApi, future: Any):
        self._api = api
        self._instance = InvalidArtifact(self)
        self._future = future

    def __getattr__(self, item: str) -> Any:
        return getattr(self._instance, item)

    def wait(self, timeout: Optional[int] = None) -> ArtifactInterface:
        if not self._instance:
            future_get = self._future.get(timeout)
            if not future_get:
                raise WaitTimeoutError(
                    "Artifact upload wait timed out, failed to fetch Artifact response"
                )
            resp = future_get.response.log_artifact_response
            if resp.error_message:
                raise ValueError(resp.error_message)
            instance = PublicArtifact.from_id(resp.artifact_id, self._api.client)
            assert instance is not None
            self._instance = instance
        assert isinstance(
            self._instance, ArtifactInterface
        ), "Insufficient permissions to fetch Artifact with id {} from {}".format(
            resp.artifact_id, self._api.client.app_url
        )
        return self._instance

    @property
    def id(self) -> Optional[str]:
        return self._instance.id

    @property
    def entity(self) -> str:
        return self._instance.entity

    @property
    def project(self) -> str:
        return self._instance.project

    @property
    def name(self) -> str:
        return self._instance.name

    @property
    def version(self) -> str:
        return self._instance.version

    @property
    def source_entity(self) -> str:
        return self._instance.source_entity

    @property
    def source_project(self) -> str:
        return self._instance.source_project

    @property
    def source_name(self) -> str:
        return self._instance.source_name

    @property
    def source_version(self) -> str:
        return self._instance.source_version

    @property
    def type(self) -> str:
        return self._instance.type

    @property
    def manifest(self) -> "ArtifactManifest":
        return self._instance.manifest

    @property
    def digest(self) -> str:
        return self._instance.digest

    @property
    def state(self) -> str:
        return self._instance.state

    @property
    def size(self) -> int:
        return self._instance.size

    @property
    def commit_hash(self) -> str:
        return self._instance.commit_hash

    @property
    def description(self) -> Optional[str]:
        return self._instance.description

    @description.setter
    def description(self, desc: Optional[str]) -> None:
        self._instance.description = desc

    @property
    def metadata(self) -> dict:
        return self._instance.metadata

    @metadata.setter
    def metadata(self, metadata: dict) -> None:
        self._instance.metadata = metadata

    @property
    def aliases(self) -> List[str]:
        return self._instance.aliases

    @aliases.setter
    def aliases(self, aliases: List[str]) -> None:
        self._instance.aliases = aliases

    def used_by(self) -> List["wandb.apis.public.Run"]:
        return self._instance.used_by()

    def logged_by(self) -> Optional["wandb.apis.public.Run"]:
        return self._instance.logged_by()

    def get_path(self, name: StrPath) -> "ArtifactManifestEntry":
        return self._instance.get_path(name)

    def get(self, name: str) -> Optional["WBValue"]:
        return self._instance.get(name)

    def download(
        self, root: Optional[str] = None, recursive: bool = False
    ) -> FilePathStr:
        return self._instance.download(root, recursive)

    def checkout(self, root: Optional[str] = None) -> str:
        return self._instance.checkout(root)

    def verify(self, root: Optional[str] = None) -> None:
        self._instance.verify(root)

    def save(self) -> None:
        self._instance.save()

    def delete(self, delete_aliases: bool = False) -> None:
        self._instance.delete(delete_aliases=delete_aliases)
