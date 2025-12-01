"""Azure storage handler."""

from __future__ import annotations

from pathlib import PurePosixPath
from types import ModuleType
from typing import TYPE_CHECKING
from urllib.parse import ParseResult, parse_qsl, urlparse

import wandb
from wandb import util
from wandb.sdk.artifacts.artifact_file_cache import get_artifact_file_cache
from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry
from wandb.sdk.artifacts.storage_handler import DEFAULT_MAX_OBJECTS, StorageHandler
from wandb.sdk.lib.hashutil import ETag
from wandb.sdk.lib.paths import FilePathStr, LogicalPath, StrPath, URIStr

if TYPE_CHECKING:
    import azure.identity  # type: ignore
    import azure.storage.blob  # type: ignore

    from wandb.sdk.artifacts.artifact import Artifact
    from wandb.sdk.artifacts.artifact_file_cache import ArtifactFileCache


class AzureHandler(StorageHandler):
    _scheme: str
    _cache: ArtifactFileCache

    def __init__(self, scheme: str = "https") -> None:
        self._scheme = scheme
        self._cache = get_artifact_file_cache()

    def can_handle(self, parsed_url: ParseResult) -> bool:
        return parsed_url.scheme == self._scheme and parsed_url.netloc.endswith(
            ".blob.core.windows.net"
        )

    def load_path(
        self,
        manifest_entry: ArtifactManifestEntry,
        local: bool = False,
    ) -> URIStr | FilePathStr:
        assert manifest_entry.ref is not None
        if not local:
            return manifest_entry.ref

        path, hit, cache_open = self._cache.check_etag_obj_path(
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
            account_url, credential=self._get_credential(account_url)
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
        artifact: Artifact,
        path: URIStr | FilePathStr,
        name: StrPath | None = None,
        checksum: bool = True,
        max_objects: int | None = None,
    ) -> list[ArtifactManifestEntry]:
        account_url, container_name, blob_name, query = self._parse_uri(path)
        path = URIStr(f"{account_url}/{container_name}/{blob_name}")

        if not checksum:
            return [
                ArtifactManifestEntry(path=name or blob_name, digest=path, ref=path)
            ]

        blob_service_client = self._get_module("azure.storage.blob").BlobServiceClient(
            account_url, credential=self._get_credential(account_url)
        )
        blob_client = blob_service_client.get_blob_client(
            container=container_name, blob=blob_name
        )
        if blob_client.exists(version_id=query.get("versionId")):
            blob_properties = blob_client.get_blob_properties(
                version_id=query.get("versionId")
            )

            if not self._is_directory_stub(blob_properties):
                return [
                    self._create_entry(
                        blob_properties,
                        path=name or PurePosixPath(blob_name).name,
                        ref=URIStr(
                            f"{account_url}/{container_name}/{blob_properties.name}"
                        ),
                    )
                ]

        entries: list[ArtifactManifestEntry] = []
        container_client = blob_service_client.get_container_client(container_name)
        max_objects = max_objects or DEFAULT_MAX_OBJECTS
        for blob_properties in container_client.list_blobs(
            name_starts_with=f"{blob_name}/"
        ):
            if len(entries) >= max_objects:
                wandb.termwarn(
                    f"Found more than {max_objects} objects under path, limiting upload "
                    f"to {max_objects} objects. Increase max_objects to upload more"
                )
                break
            if not self._is_directory_stub(blob_properties):
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

    def _get_credential(
        self, account_url: str
    ) -> azure.identity.DefaultAzureCredential | str:
        # NOTE: Always returns default credential for reinit="create_new" runs.
        if (
            wandb.run
            and wandb.run.settings.azure_account_url_to_access_key is not None
            and account_url in wandb.run.settings.azure_account_url_to_access_key
        ):
            return wandb.run.settings.azure_account_url_to_access_key[account_url]
        return self._get_module("azure.identity").DefaultAzureCredential()

    def _parse_uri(self, uri: str) -> tuple[str, str, str, dict[str, str]]:
        parsed_url = urlparse(uri)
        query = dict(parse_qsl(parsed_url.query))
        account_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
        _, container_name, blob_name = parsed_url.path.split("/", 2)
        return account_url, container_name, blob_name, query

    def _create_entry(
        self,
        blob_properties: azure.storage.blob.BlobProperties,
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

    def _is_directory_stub(
        self, blob_properties: azure.storage.blob.BlobProperties
    ) -> bool:
        return (
            blob_properties.has_key("metadata")
            and "hdi_isfolder" in blob_properties.metadata
            and blob_properties.metadata["hdi_isfolder"] == "true"
        )
