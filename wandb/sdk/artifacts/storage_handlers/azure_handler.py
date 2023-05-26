"""Azure storage handler."""
from pathlib import PurePosixPath
from types import ModuleType
from typing import TYPE_CHECKING, Dict, Optional, Sequence, Tuple, Union
from urllib.parse import ParseResult, parse_qsl, urlparse

from wandb import util
from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry
from wandb.sdk.artifacts.artifacts_cache import get_artifacts_cache
from wandb.sdk.artifacts.storage_handler import DEFAULT_MAX_OBJECTS, StorageHandler
from wandb.sdk.lib.hashutil import ETag
from wandb.sdk.lib.paths import FilePathStr, LogicalPath, StrPath, URIStr

if TYPE_CHECKING:
    import azure.storage.blob  # type: ignore

    from wandb.sdk.artifacts.artifact import Artifact as ArtifactInterface


class AzureHandler(StorageHandler):
    def can_handle(self, parsed_url: "ParseResult") -> bool:
        return parsed_url.scheme == "https" and parsed_url.netloc.endswith(
            ".blob.core.windows.net"
        )

    def load_path(
        self,
        manifest_entry: "ArtifactManifestEntry",
        local: bool = False,
    ) -> Union[URIStr, FilePathStr]:
        assert manifest_entry.ref is not None
        if not local:
            return manifest_entry.ref

        path, hit, cache_open = get_artifacts_cache().check_etag_obj_path(
            URIStr(manifest_entry.ref),
            ETag(manifest_entry.digest),
            manifest_entry.size or 0,
        )
        if hit:
            return path

        account_url, container_name, blob_name, query = self._parse_uri(
            manifest_entry.ref
        )
        version_id = manifest_entry.extra.get("versionID")
        blob_service_client = self._get_module("azure.storage.blob").BlobServiceClient(
            account_url,
            credential=self._get_module("azure.identity").DefaultAzureCredential(),
        )
        blob_client = blob_service_client.get_blob_client(
            container=container_name, blob=blob_name
        )
        if version_id is None:
            # Try current version, then all versions.
            try:
                downloader = blob_client.download_blob(
                    etag=manifest_entry.digest,
                    match_condition=self._get_module(
                        "azure.core"
                    ).MatchConditions.IfNotModified,
                )
            except self._get_module("azure.core.exceptions").ResourceModifiedError:
                container_client = blob_service_client.get_container_client(
                    container_name
                )
                for blob_properties in container_client.walk_blobs(
                    name_starts_with=blob_name, include=["versions"]
                ):
                    if (
                        blob_properties.name == blob_name
                        and blob_properties.etag == manifest_entry.digest
                        and blob_properties.version_id is not None
                    ):
                        downloader = blob_client.download_blob(
                            version_id=blob_properties.version_id
                        )
                        break
                else:  # didn't break
                    raise ValueError(
                        f"Couldn't find blob version for {manifest_entry.ref} matching "
                        f"etag {manifest_entry.digest}."
                    )
        else:
            downloader = blob_client.download_blob(version_id=version_id)
        with cache_open(mode="wb") as f:
            downloader.readinto(f)
        return path

    def store_path(
        self,
        artifact: "ArtifactInterface",
        path: Union[URIStr, FilePathStr],
        name: Optional[StrPath] = None,
        checksum: bool = True,
        max_objects: Optional[int] = None,
    ) -> Sequence["ArtifactManifestEntry"]:
        account_url, container_name, blob_name, query = self._parse_uri(path)
        path = URIStr(f"{account_url}/{container_name}/{blob_name}")

        if not checksum:
            return [
                ArtifactManifestEntry(path=name or blob_name, digest=path, ref=path)
            ]

        blob_service_client = self._get_module("azure.storage.blob").BlobServiceClient(
            account_url,
            credential=self._get_module("azure.identity").DefaultAzureCredential(),
        )
        blob_client = blob_service_client.get_blob_client(
            container=container_name, blob=blob_name
        )
        if blob_client.exists(version_id=query.get("versionId")):
            blob_properties = blob_client.get_blob_properties(
                version_id=query.get("versionId")
            )
            return [
                self._create_entry(
                    blob_properties,
                    path=name or PurePosixPath(blob_name).name,
                    ref=URIStr(
                        f"{account_url}/{container_name}/{blob_properties.name}"
                    ),
                )
            ]

        entries = []
        container_client = blob_service_client.get_container_client(container_name)
        max_objects = max_objects or DEFAULT_MAX_OBJECTS
        for i, blob_properties in enumerate(
            container_client.list_blobs(name_starts_with=f"{blob_name}/")
        ):
            if i >= max_objects:
                raise ValueError(
                    f"Exceeded {max_objects} objects tracked, pass max_objects to "
                    f"add_reference"
                )
            suffix = PurePosixPath(blob_properties.name).relative_to(blob_name)
            entries.append(
                self._create_entry(
                    blob_properties,
                    path=LogicalPath(name) / suffix if name else suffix,
                    ref=URIStr(
                        f"{account_url}/{container_name}/{blob_properties.name}"
                    ),
                )
            )
        return entries

    def _get_module(self, name: str) -> ModuleType:
        module = util.get_module(
            name,
            lazy=False,
            required="Azure references require the azure library, run "
            "pip install wandb[azure]",
        )
        assert isinstance(module, ModuleType)
        return module

    def _parse_uri(self, uri: str) -> Tuple[str, str, str, Dict[str, str]]:
        parsed_url = urlparse(uri)
        query = dict(parse_qsl(parsed_url.query))
        account_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
        _, container_name, blob_name = parsed_url.path.split("/", 2)
        return account_url, container_name, blob_name, query

    def _create_entry(
        self,
        blob_properties: "azure.storage.blob.BlobProperties",
        path: StrPath,
        ref: URIStr,
    ) -> ArtifactManifestEntry:
        extra = {"etag": blob_properties.etag.strip('"')}
        if blob_properties.version_id:
            extra["versionID"] = blob_properties.version_id
        return ArtifactManifestEntry(
            path=path,
            ref=ref,
            digest=blob_properties.etag.strip('"'),
            size=blob_properties.size,
            extra=extra,
        )
