"""Azure storage handler."""

from __future__ import annotations

import logging
from collections import deque
from pathlib import PurePosixPath
from typing import TYPE_CHECKING
from urllib.parse import ParseResult, parse_qsl, urlparse

import wandb
from wandb.sdk.artifacts.artifact_file_cache import get_artifact_file_cache
from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry
from wandb.sdk.artifacts.storage_handler import DEFAULT_MAX_OBJECTS, StorageHandler
from wandb.sdk.lib.hashutil import ETag
from wandb.sdk.lib.paths import FilePathStr, LogicalPath, StrPath, URIStr

if TYPE_CHECKING:
    from azure.identity import DefaultAzureCredential  # type: ignore[import-not-found]
    from azure.storage.blob import BlobProperties  # type: ignore[import-not-found]
    from typing_extensions import Never

    from wandb.sdk.artifacts.artifact import Artifact
    from wandb.sdk.artifacts.artifact_file_cache import ArtifactFileCache

logger = logging.getLogger(__name__)


def _handle_azure_import_error(exc: ImportError) -> Never:
    # We handle the ImportError this way for continuity/backward compatibility.
    # In a later (breaking) change, we should really just raise a proper ImportError
    # or a custom subclass of it.
    logger.exception(f"Error importing optional module {exc.name!r}")
    raise wandb.Error(
        "Azure references require the azure library, run pip install wandb[azure]"
    )


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
        try:
            from azure.core import MatchConditions  # type: ignore
            from azure.core.exceptions import ResourceModifiedError  # type: ignore
            from azure.storage.blob import BlobServiceClient
        except ImportError as e:
            _handle_azure_import_error(e)

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

        account_url, container_name, blob_name, _ = _parse_uri(manifest_entry.ref)
        blob_service_client = BlobServiceClient(
            account_url, credential=_get_credential(account_url)
        )
        blob_client = blob_service_client.get_blob_client(
            container=container_name, blob=blob_name
        )
        blob_etag = manifest_entry.digest
        if (version_id := manifest_entry.extra.get("versionID")) is None:
            # Try current version, then all versions.
            try:
                downloader = blob_client.download_blob(
                    etag=blob_etag,
                    match_condition=MatchConditions.IfNotModified,
                )
            except ResourceModifiedError:
                container_client = blob_service_client.get_container_client(
                    container_name
                )
                for blob_properties in container_client.walk_blobs(
                    name_starts_with=blob_name, include=["versions"]
                ):
                    if (
                        blob_properties.name == blob_name
                        and blob_properties.etag == blob_etag
                        and blob_properties.version_id is not None
                    ):
                        downloader = blob_client.download_blob(
                            version_id=blob_properties.version_id
                        )
                        break
                else:  # didn't break
                    raise ValueError(
                        f"Couldn't find blob version for {manifest_entry.ref} matching etag {blob_etag}."
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
        try:
            from azure.storage.blob import BlobServiceClient
        except ImportError as e:
            _handle_azure_import_error(e)

        account_url, container_name, blob_name, query = _parse_uri(path)
        path = URIStr(f"{account_url}/{container_name}/{blob_name}")

        if not checksum:
            return [
                ArtifactManifestEntry(path=name or blob_name, digest=path, ref=path)
            ]

        blob_service_client = BlobServiceClient(
            account_url, credential=_get_credential(account_url)
        )
        blob_client = blob_service_client.get_blob_client(
            container=container_name, blob=blob_name
        )
        if (
            (version_id := query.get("versionId"))
            and blob_client.exists(version_id=version_id)
            and not _is_directory_stub(
                blob_props := blob_client.get_blob_properties(version_id=version_id)
            )
        ):
            return [
                _create_entry(
                    blob_props,
                    path=name or PurePosixPath(blob_name).name,
                    ref=f"{account_url}/{container_name}/{blob_props.name}",
                )
            ]

        entries: deque[ArtifactManifestEntry] = deque()
        container_client = blob_service_client.get_container_client(container_name)
        max_objects = max_objects or DEFAULT_MAX_OBJECTS
        for blob_props in container_client.list_blobs(name_starts_with=f"{blob_name}/"):
            if len(entries) >= max_objects:
                wandb.termwarn(
                    f"Found more than {max_objects} objects under path, limiting upload "
                    f"to {max_objects} objects. Increase max_objects to upload more"
                )
                break
            if not _is_directory_stub(blob_props):
                suffix = PurePosixPath(blob_props.name).relative_to(blob_name)
                entries.append(
                    _create_entry(
                        blob_props,
                        path=LogicalPath(name) / suffix if name else suffix,
                        ref=f"{account_url}/{container_name}/{blob_props.name}",
                    )
                )

        return list(entries)


def _get_credential(account_url: str) -> DefaultAzureCredential | str:
    try:
        from azure.identity import DefaultAzureCredential
    except ImportError as e:
        _handle_azure_import_error(e)

    # NOTE: Always returns default credential for reinit="create_new" runs.
    if (
        (run := wandb.run)
        and (url2key := run.settings.azure_account_url_to_access_key)
        and (access_key := url2key.get(account_url))
    ):
        return access_key
    return DefaultAzureCredential()


def _parse_uri(uri: str) -> tuple[str, str, str, dict[str, str]]:
    parsed_url = urlparse(uri)
    query = dict(parse_qsl(parsed_url.query))
    account_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
    _, container_name, blob_name = parsed_url.path.split("/", 2)
    return account_url, container_name, blob_name, query


def _create_entry(
    blob_properties: BlobProperties,
    path: StrPath,
    ref: URIStr,
) -> ArtifactManifestEntry:
    etag = blob_properties.etag.strip('"')
    extra = {"etag": etag}
    if version_id := blob_properties.version_id:
        extra["versionID"] = version_id
    return ArtifactManifestEntry(
        path=path,
        ref=ref,
        digest=etag,
        size=blob_properties.size,
        extra=extra,
    )


def _is_directory_stub(blob_properties: BlobProperties) -> bool:
    return bool(
        (metadata := blob_properties.metadata)
        and metadata.get("hdi_isfolder") == "true"
    )
