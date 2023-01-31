"""Batching file prepare requests to our API."""

import concurrent.futures
import os
import queue
import shutil
import threading
from typing import TYPE_CHECKING, NamedTuple, Optional, Union, cast

from wandb.filesync import dir_watcher, step_upload
from wandb.sdk.lib import filesystem, runid

if TYPE_CHECKING:
    import tempfile

    from wandb.filesync import stats
    from wandb.sdk.interface import artifacts
    from wandb.sdk.internal import artifacts as internal_artifacts
    from wandb.sdk.internal import internal_api


class RequestUpload(NamedTuple):
    path: str
    save_name: dir_watcher.SaveName
    copy: bool


class RequestStoreManifestFiles(NamedTuple):
    manifest: "artifacts.ArtifactManifest"
    artifact_id: str
    save_fn: "internal_artifacts.SaveFn"


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
    ) -> None:
        self._api = api
        self._tempdir = tempdir
        self._request_queue = request_queue
        self._output_queue = output_queue
        self._stats = stats

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
                    )
                )
            elif isinstance(req, RequestStoreManifestFiles):
                for entry in req.manifest.entries.values():
                    if entry.local_path:
                        # This stupid thing is needed so the closure works correctly.
                        def make_save_fn_with_entry(
                            save_fn: "internal_artifacts.SaveFn",
                            entry: "artifacts.ArtifactManifestEntry",
                        ) -> step_upload.SaveFn:
                            return lambda progress_callback: save_fn(
                                entry, progress_callback
                            )

                        self._stats.init_file(
                            entry.local_path,
                            cast(int, entry.size),
                            is_artifact_file=True,
                        )
                        self._output_queue.put(
                            step_upload.RequestUpload(
                                entry.local_path,
                                dir_watcher.SaveName(
                                    entry.path
                                ),  # typecast might not be legit
                                req.artifact_id,
                                entry.digest,
                                False,
                                make_save_fn_with_entry(req.save_fn, entry),
                                entry.digest,
                            )
                        )
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

    def start(self) -> None:
        self._thread.start()

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def finish(self) -> None:
        self._request_queue.put(RequestFinish(None))
