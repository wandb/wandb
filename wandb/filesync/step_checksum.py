"""Batching file prepare requests to our API."""

import asyncio
import concurrent.futures
import functools
import os
import queue
import shutil
import threading
from typing import TYPE_CHECKING, List, NamedTuple, Optional, Union, cast

from wandb.filesync import step_upload
from wandb.sdk.lib import filesystem, runid
from wandb.sdk.lib.paths import LogicalPath

if TYPE_CHECKING:
    import tempfile

    from wandb.filesync import stats
    from wandb.filesync.step_prepare import ResponsePrepare, StepPrepare
    from wandb.sdk.artifacts import artifact_saver
    from wandb.sdk.artifacts.artifact_manifest import ArtifactManifest
    from wandb.sdk.interface.artifacts import ArtifactManifestEntry
    from wandb.sdk.internal import internal_api


class RequestUpload(NamedTuple):
    path: str
    save_name: LogicalPath
    copy: bool


class RequestStoreManifestFiles(NamedTuple):
    manifest: "ArtifactManifest"
    artifact_id: str
    prepare_step: "StepPrepare"
    save_fn: "artifact_saver.SaveFn"
    save_fn_async: "artifact_saver.SaveFnAsync"
    interleave_uploads: bool


class RequestCommitArtifact(NamedTuple):
    artifact_id: str
    finalize: bool
    before_commit: step_upload.PreCommitFn
    result_future: "concurrent.futures.Future[None]"


class RequestFinish(NamedTuple):
    callback: Optional[step_upload.OnRequestFinishFn]


Event = Union[
    RequestUpload, RequestStoreManifestFiles, RequestCommitArtifact, RequestFinish
]


class StepChecksum:
    def __init__(
        self,
        api: "internal_api.Api",
        tempdir: "tempfile.TemporaryDirectory",
        request_queue: "queue.Queue[Event]",
        output_queue: "queue.Queue[step_upload.Event]",
        stats: "stats.Stats",
        artifact_tracker: Optional[step_upload.StepUpload],
    ) -> None:
        self._api = api
        self._tempdir = tempdir
        self._request_queue = request_queue
        self._output_queue = output_queue
        self._stats = stats
        self._artifact_tracker = artifact_tracker

        self._thread = threading.Thread(target=self._thread_body)
        self._thread.daemon = True

    def _thread_body(self) -> None:
        while True:
            req = self._request_queue.get()
            if isinstance(req, RequestUpload):
                path = req.path
                if req.copy:
                    path = os.path.join(
                        self._tempdir.name,
                        f"{runid.generate_id()}-{req.save_name}",
                    )
                    filesystem.mkdir_exists_ok(os.path.dirname(path))
                    try:
                        # certain linux distros throw an exception when copying
                        # large files: https://bugs.python.org/issue43743
                        shutil.copy2(req.path, path)
                    except OSError:
                        shutil._USE_CP_SENDFILE = False  # type: ignore[attr-defined]
                        shutil.copy2(req.path, path)
                self._stats.init_file(req.save_name, os.path.getsize(path))
                self._output_queue.put(
                    step_upload.RequestUpload(
                        path,
                        req.save_name,
                        None,
                        None,
                        req.copy,
                        None,
                        None,
                        None,
                    )
                )
            elif isinstance(req, RequestStoreManifestFiles):
                if req.interleave_uploads:
                    asyncio.run(self._interleave_uploads(req))
                else:
                    for entry in asyncio.run(self._prepare_batches_early(req)):
                        self.start_upload(entry, req)
            elif isinstance(req, RequestCommitArtifact):
                self._output_queue.put(
                    step_upload.RequestCommitArtifact(
                        req.artifact_id,
                        req.finalize,
                        req.before_commit,
                        req.result_future,
                    )
                )
            elif isinstance(req, RequestFinish):
                break
            else:
                raise Exception("internal error")

        self._output_queue.put(step_upload.RequestFinish(req.callback))

    async def _prepare_entry(
        self, entry: "ArtifactManifestEntry", req: RequestStoreManifestFiles
    ) -> Optional["ResponsePrepare"]:
        if not entry.local_path:
            return
        response = await req.prepare_step.prepare_async(
            {
                "artifactID": req.artifact_id,
                "artifactManifestID": req.artifact_manifest_id,
                "name": entry.path,
                "md5": entry.digest,
            }
        )
        entry.birth_artifact_id = response.birth_artifact_id
        entry._upload_url = response.upload_url
        entry._upload_headers = response.upload_headers or {}
        return entry

    async def _prepare_batches_early(
        self, req: RequestStoreManifestFiles
    ) -> List["ArtifactManifestEntry"]:
        entries = [entry for entry in req.manifest.entries.values() if entry.local_path]
        return await asyncio.gather(
            *[self._prepare_entry(entry, req) for entry in entries]
        )

    def start_upload(
        self, entry: "ArtifactManifestEntry", req: RequestStoreManifestFiles
    ) -> None:
        self._stats.init_file(
            entry.local_path,
            cast(int, entry.size),
            is_artifact_file=True,
        )
        self._output_queue.put(
            step_upload.RequestUpload(
                entry.local_path,
                entry.path,
                req.artifact_id,
                entry.digest,
                False,
                functools.partial(req.save_fn, entry),
                functools.partial(req.save_fn_async, entry),
                entry.digest,
            )
        )

    async def _upload_entry(
        self, entry: "ArtifactManifestEntry", req: RequestStoreManifestFiles
    ) -> None:
        self.start_upload(await self._prepare_entry(entry, req))

    async def _interleave_uploads(self, req: RequestStoreManifestFiles) -> None:
        entries = [entry for entry in req.manifest.entries.values() if entry.local_path]
        asyncio.gather(*[self._upload_entry(entry, req) for entry in entries])

    def start(self) -> None:
        self._thread.start()

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def finish(self) -> None:
        self._request_queue.put(RequestFinish(None))
