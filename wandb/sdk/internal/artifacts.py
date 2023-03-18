import concurrent.futures
import json
import os
import sys
import tempfile
from typing import TYPE_CHECKING, Awaitable, Dict, List, Optional, Sequence

import wandb
import wandb.filesync.step_prepare
from wandb import env, util
from wandb.sdk.interface.artifacts import ArtifactManifest, ArtifactManifestEntry
from wandb.sdk.lib.filesystem import mkdir_exists_ok
from wandb.sdk.lib.hashutil import B64MD5, b64_to_hex_id, md5_file_b64
from wandb.util import FilePathStr

if TYPE_CHECKING:
    from wandb.sdk.internal.internal_api import Api as InternalApi
    from wandb.sdk.internal.progress import ProgressFn

    from .file_pusher import FilePusher

    if sys.version_info >= (3, 8):
        from typing import Protocol
    else:
        from typing_extensions import Protocol

    class SaveFn(Protocol):
        def __call__(
            self, entry: ArtifactManifestEntry, progress_callback: "ProgressFn"
        ) -> bool:
            pass

    class SaveFnAsync(Protocol):
        def __call__(
            self, entry: ArtifactManifestEntry, progress_callback: "ProgressFn"
        ) -> Awaitable[bool]:
            pass


class ArtifactSaver:
    _server_artifact: Optional[Dict]  # TODO better define this dict

    def __init__(
        self,
        api: "InternalApi",
        digest: str,
        manifest_json: Dict,
        file_pusher: "FilePusher",
        is_user_created: bool = False,
    ) -> None:
        self._api = api
        self._file_pusher = file_pusher
        self._digest = digest
        self._manifest = ArtifactManifest.from_manifest_json(manifest_json)
        self._is_user_created = is_user_created
        self._server_artifact = None

    def save(
        self,
        type: str,
        name: str,
        client_id: str,
        sequence_client_id: str,
        distributed_id: Optional[str] = None,
        finalize: bool = True,
        metadata: Optional[Dict] = None,
        description: Optional[str] = None,
        aliases: Optional[Sequence[str]] = None,
        labels: Optional[List[str]] = None,
        use_after_commit: bool = False,
        incremental: bool = False,
        history_step: Optional[int] = None,
    ) -> Optional[Dict]:
        try:
            return self._save_internal(
                type,
                name,
                client_id,
                sequence_client_id,
                distributed_id,
                finalize,
                metadata,
                description,
                aliases,
                labels,
                use_after_commit,
                incremental,
                history_step,
            )
        finally:
            self._cleanup_staged_entries()

    def _save_internal(
        self,
        type: str,
        name: str,
        client_id: str,
        sequence_client_id: str,
        distributed_id: Optional[str] = None,
        finalize: bool = True,
        metadata: Optional[Dict] = None,
        description: Optional[str] = None,
        aliases: Optional[Sequence[str]] = None,
        labels: Optional[List[str]] = None,
        use_after_commit: bool = False,
        incremental: bool = False,
        history_step: Optional[int] = None,
    ) -> Optional[Dict]:
        aliases = aliases or []
        alias_specs = []
        for alias in aliases:
            if ":" in alias:
                # Users can explicitly alias this artifact to names
                # other than the primary one passed in by using the
                # 'secondaryName:alias' notation.
                idx = alias.index(":")
                artifact_collection_name = alias[: idx - 1]
                tag = alias[idx + 1 :]
            else:
                artifact_collection_name = name
                tag = alias
            alias_specs.append(
                {
                    "artifactCollectionName": artifact_collection_name,
                    "alias": tag,
                }
            )

        """Returns the server artifact."""
        self._server_artifact, latest = self._api.create_artifact(
            type,
            name,
            self._digest,
            metadata=metadata,
            aliases=alias_specs,
            labels=labels,
            description=description,
            is_user_created=self._is_user_created,
            distributed_id=distributed_id,
            client_id=client_id,
            sequence_client_id=sequence_client_id,
            enable_digest_deduplication=use_after_commit,  # Reuse logical duplicates in the `use_artifact` flow
            history_step=history_step,
        )

        # TODO(artifacts):
        #   if it's committed, all is good. If it's committing, just moving ahead isn't necessarily
        #   correct. It may be better to poll until it's committed or failed, and then decided what to
        #   do
        assert self._server_artifact is not None  # mypy optionality unwrapper
        artifact_id = self._server_artifact["id"]
        latest_artifact_id = latest["id"] if latest else None
        if (
            self._server_artifact["state"] == "COMMITTED"
            or self._server_artifact["state"] == "COMMITTING"
        ):
            # TODO: update aliases, labels, description etc?
            if use_after_commit:
                self._api.use_artifact(artifact_id)
            return self._server_artifact
        elif (
            self._server_artifact["state"] != "PENDING"
            and self._server_artifact["state"] != "DELETED"
        ):
            raise Exception(
                'Unknown artifact state "{}"'.format(self._server_artifact["state"])
            )

        manifest_type = "FULL"
        manifest_filename = "wandb_manifest.json"
        if incremental:
            manifest_type = "INCREMENTAL"
            manifest_filename = "wandb_manifest.incremental.json"
        elif distributed_id:
            manifest_type = "PATCH"
            manifest_filename = "wandb_manifest.patch.json"
        artifact_manifest_id, _ = self._api.create_artifact_manifest(
            manifest_filename,
            "",
            artifact_id,
            base_artifact_id=latest_artifact_id,
            include_upload=False,
            type=manifest_type,
        )

        step_prepare = wandb.filesync.step_prepare.StepPrepare(
            self._api, 0.1, 0.01, 1000
        )  # TODO: params
        step_prepare.start()

        # Upload Artifact "L1" files, the actual artifact contents
        self._file_pusher.store_manifest_files(
            self._manifest,
            artifact_id,
            lambda entry, progress_callback: self._manifest.storage_policy.store_file_sync(
                artifact_id,
                artifact_manifest_id,
                entry,
                step_prepare,
                progress_callback=progress_callback,
            ),
            lambda entry, progress_callback: self._manifest.storage_policy.store_file_async(
                artifact_id,
                artifact_manifest_id,
                entry,
                step_prepare,
                progress_callback=progress_callback,
            ),
        )

        def before_commit() -> None:
            self._resolve_client_id_manifest_references()
            with tempfile.NamedTemporaryFile("w+", suffix=".json", delete=False) as fp:
                path = os.path.abspath(fp.name)
                json.dump(self._manifest.to_manifest_json(), fp, indent=4)
            digest = md5_file_b64(path)
            if distributed_id or incremental:
                # If we're in the distributed flow, we want to update the
                # patch manifest we created with our finalized digest.
                _, resp = self._api.update_artifact_manifest(
                    artifact_manifest_id,
                    digest=digest,
                )
            else:
                # In the regular flow, we can recreate the full manifest with the
                # updated digest.
                #
                # NOTE: We do this for backwards compatibility with older backends
                # that don't support the 'updateArtifactManifest' API.
                _, resp = self._api.create_artifact_manifest(
                    manifest_filename,
                    digest,
                    artifact_id,
                    base_artifact_id=latest_artifact_id,
                )

            # We're duplicating the file upload logic a little, which isn't great.
            upload_url = resp["uploadUrl"]
            upload_headers = resp["uploadHeaders"]
            extra_headers = {}
            for upload_header in upload_headers:
                key, val = upload_header.split(":", 1)
                extra_headers[key] = val
            with open(path, "rb") as fp2:
                self._api.upload_file_retry(
                    upload_url,
                    fp2,
                    extra_headers=extra_headers,
                )

        commit_result: "concurrent.futures.Future[None]" = concurrent.futures.Future()

        # This will queue the commit. It will only happen after all the file uploads are done
        self._file_pusher.commit_artifact(
            artifact_id,
            finalize=finalize,
            before_commit=before_commit,
            result_future=commit_result,
        )

        # Block until all artifact files are uploaded and the
        # artifact is committed.
        try:
            commit_result.result()
        finally:
            step_prepare.shutdown()

        if finalize and use_after_commit:
            self._api.use_artifact(artifact_id)

        return self._server_artifact

    def _resolve_client_id_manifest_references(self) -> None:
        for entry_path in self._manifest.entries:
            entry = self._manifest.entries[entry_path]
            if entry.ref is not None:
                if entry.ref.startswith("wandb-client-artifact:"):
                    client_id = util.host_from_path(entry.ref)
                    artifact_file_path = util.uri_from_path(entry.ref)
                    artifact_id = self._api._resolve_client_id(client_id)
                    if artifact_id is None:
                        raise RuntimeError(f"Could not resolve client id {client_id}")
                    entry.ref = util.URIStr(
                        "wandb-artifact://{}/{}".format(
                            b64_to_hex_id(B64MD5(artifact_id)), artifact_file_path
                        )
                    )

    def _cleanup_staged_entries(self) -> None:
        """Remove all staging copies of local files.

        We made a staging copy of each local file to freeze it at "add" time.
        We need to delete them once we've uploaded the file or confirmed we
        already have a committed copy.
        """
        staging_dir = get_staging_dir()
        for entry in self._manifest.entries.values():
            if entry.local_path and entry.local_path.startswith(staging_dir):
                try:
                    os.remove(entry.local_path)
                except OSError:
                    pass


def get_staging_dir() -> FilePathStr:
    path = os.path.join(env.get_data_dir(), "artifacts", "staging")
    try:
        mkdir_exists_ok(path)
    except OSError as e:
        raise PermissionError(
            f"Unable to write staging files to {path}. To fix this problem, please set "
            f"{env.DATA_DIR} to a directory where you have the necessary write access."
        ) from e

    return FilePathStr(os.path.abspath(os.path.expanduser(path)))
