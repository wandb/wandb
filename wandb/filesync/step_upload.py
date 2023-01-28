"""Batching file prepare requests to our API."""

import asyncio
import concurrent.futures
import logging
import os
import queue
import sys
import threading
from typing import (
    TYPE_CHECKING,
    Awaitable,
    Callable,
    MutableMapping,
    MutableSequence,
    MutableSet,
    NamedTuple,
    Optional,
    Union,
)

import wandb.env
import wandb.util
from wandb.errors.term import termerror
from wandb.filesync import upload_job

if TYPE_CHECKING:
    from wandb.filesync import dir_watcher, stats
    from wandb.sdk.internal import file_stream, internal_api, progress

    if sys.version_info >= (3, 8):
        from typing import TypedDict
    else:
        from typing_extensions import TypedDict

    class ArtifactStatus(TypedDict):
        finalize: bool
        pending_count: int
        commit_requested: bool
        pre_commit_callbacks: MutableSet["PreCommitFn"]
        result_futures: MutableSet["concurrent.futures.Future[None]"]


PreCommitFn = Callable[[], None]
OnRequestFinishFn = Callable[[], None]
SaveFn = Callable[["progress.ProgressFn"], bool]
SaveFnAsync = Callable[["progress.ProgressFn"], Awaitable[bool]]

logger = logging.getLogger(__name__)


class RequestUpload(NamedTuple):
    path: str
    save_name: "dir_watcher.SaveName"
    artifact_id: Optional[str]
    md5: Optional[str]
    copied: bool
    save_fn: Optional[SaveFn]
    save_fn_async: Optional[SaveFnAsync]
    digest: Optional[str]


class RequestCommitArtifact(NamedTuple):
    artifact_id: str
    finalize: bool
    before_commit: PreCommitFn
    result_fut: "concurrent.futures.Future[None]"


class RequestFinish(NamedTuple):
    callback: Optional[OnRequestFinishFn]


Event = Union[
    RequestUpload, RequestCommitArtifact, RequestFinish, upload_job.EventJobDone
]


class StepUpload:
    def __init__(
        self,
        api: "internal_api.Api",
        stats: "stats.Stats",
        event_queue: "queue.Queue[Event]",
        max_jobs: int,
        file_stream: "file_stream.FileStreamApi",
        silent: bool = False,
    ) -> None:
        self._api = api
        self._stats = stats
        self._event_queue = event_queue
        self._file_stream = file_stream

        self._thread = threading.Thread(target=self._thread_body)
        self._thread.daemon = True

        self._pool = concurrent.futures.ThreadPoolExecutor(
            thread_name_prefix="wandb-upload",
            max_workers=max_jobs,
        )

        self._loop = asyncio.new_event_loop()
        self._loop.set_default_executor(self._pool)
        self._loop_thread = threading.Thread(
            target=self._loop.run_forever,
            daemon=True,
            name="wandb-upload-async",
        )
        self._async_concurrency_limiter = asyncio.Semaphore(500, loop=self._loop)

        # Indexed by files' `save_name`'s, which are their ID's in the Run.
        self._running_jobs: MutableMapping[dir_watcher.SaveName, RequestUpload] = {}
        self._pending_jobs: MutableSequence[RequestUpload] = []

        self._artifacts: MutableMapping[str, "ArtifactStatus"] = {}

        self.silent = silent

    def _thread_body(self) -> None:
        event: Optional[Event]
        # Wait for event in the queue, and process one by one until a
        # finish event is received
        finish_callback = None
        while True:
            event = self._event_queue.get()
            if isinstance(event, RequestFinish):
                finish_callback = event.callback
                break
            self._handle_event(event)

        # We've received a finish event. At this point, further Upload requests
        # are invalid.

        # After a finish event is received, iterate through the event queue
        # one by one and process all remaining events.
        while True:
            try:
                event = self._event_queue.get(True, 0.2)
            except queue.Empty:
                event = None
            if event:
                self._handle_event(event)
            elif not self._running_jobs:
                # Queue was empty and no jobs left.
                if finish_callback:
                    finish_callback()
                break

    def _handle_event(self, event: Event) -> None:
        if isinstance(event, upload_job.EventJobDone):
            job = event.job

            if event.exc is not None:
                logger.exception(
                    "Failed to upload file: %s", job.path, exc_info=event.exc
                )

            if job.artifact_id:
                if event.exc is None:
                    self._artifacts[job.artifact_id]["pending_count"] -= 1
                    self._maybe_commit_artifact(job.artifact_id)
                else:
                    if not self.silent:
                        termerror(
                            "Uploading artifact file failed. Artifact won't be committed."
                        )
                    self._fail_artifact_futures(job.artifact_id, event.exc)
            self._running_jobs.pop(job.save_name)
            # If we have any pending jobs, start one now
            if self._pending_jobs:
                event = self._pending_jobs.pop(0)
                self._start_upload_job(event)
        elif isinstance(event, RequestCommitArtifact):
            if event.artifact_id not in self._artifacts:
                self._init_artifact(event.artifact_id)
            self._artifacts[event.artifact_id]["commit_requested"] = True
            self._artifacts[event.artifact_id]["finalize"] = event.finalize
            self._artifacts[event.artifact_id]["pre_commit_callbacks"].add(
                event.before_commit
            )
            self._artifacts[event.artifact_id]["result_futures"].add(event.result_fut)
            self._maybe_commit_artifact(event.artifact_id)
        elif isinstance(event, RequestUpload):
            if event.artifact_id is not None:
                if event.artifact_id not in self._artifacts:
                    self._init_artifact(event.artifact_id)
                self._artifacts[event.artifact_id]["pending_count"] += 1
            self._start_upload_job(event)
        else:
            raise Exception("Programming error: unhandled event: %s" % str(event))

    def _start_upload_job(self, event: RequestUpload) -> None:
        # Operations on a single backend file must be serialized. if
        # we're already uploading this file, put the event on the
        # end of the queue
        if event.save_name in self._running_jobs:
            self._pending_jobs.append(event)
            return

        if event.save_fn_async is not None and wandb.env.get_use_async_upload():
            self._spawn_upload_async(event, event.save_fn_async)
        else:
            self._spawn_upload_sync(event)

    def _spawn_upload_sync(self, event: RequestUpload) -> None:
        """Spawns an upload job, and handles the bookkeeping of `self._running_jobs`.

        Context: it's important that, whenever we add an entry to `self._running_jobs`,
        we ensure that a corresponding `EventJobDone` message will eventually get handled;
        otherwise, the `_running_jobs` entry will never get removed, and the StepUpload
        will never shut down.

        The sole purpose of this function is to make sure that the code that adds an entry
        to `self._running_jobs` is textually right next to the code that eventually enqueues
        the `EventJobDone` message. This should help keep them in sync.
        """

        # Adding the entry to `self._running_jobs` MUST happen in the main thread,
        # NOT in the job that gets submitted to the thread-pool, to guard against
        # this sequence of events:
        # - StepUpload receives a RequestUpload
        #     ...and therefore spawns a thread to do the upload
        # - StepUpload receives a RequestFinish
        #     ...and checks `self._running_jobs` to see if there are any tasks to wait for...
        #     ...and there are none, because the addition to `self._running_jobs` happens in
        #        the background thread, which the scheduler hasn't yet run...
        #     ...so the StepUpload shuts down. Even though we haven't uploaded the file!
        #
        # This would be very bad!
        # So, this line has to happen _outside_ the `pool.submit()`.
        self._running_jobs[event.save_name] = event

        def run_and_notify() -> None:
            try:
                self._do_upload_sync(event)
            finally:
                self._event_queue.put(
                    upload_job.EventJobDone(event, exc=sys.exc_info()[1])
                )

        self._pool.submit(run_and_notify)

    def _spawn_upload_async(
        self, event: RequestUpload, save_fn_async: SaveFnAsync
    ) -> None:
        """Equivalent to _spawn_upload_sync, but uses the async event loop instead of a thread."""

        self._running_jobs[event.save_name] = event

        async def run_and_notify() -> None:
            try:
                await self._do_upload_async(event, save_fn_async)
            finally:
                self._event_queue.put(
                    upload_job.EventJobDone(event, exc=sys.exc_info()[1])
                )

        self._loop.call_soon_threadsafe(
            self._loop.create_task,
            run_and_notify(),
        )

    def _do_upload_sync(self, event: RequestUpload) -> None:
        job = upload_job.UploadJob(
            self._stats,
            self._api,
            self._file_stream,
            self.silent,
            event.save_name,
            event.path,
            event.artifact_id,
            event.md5,
            event.copied,
            event.save_fn,
            event.digest,
        )
        job.run()

    async def _do_upload_async(
        self, event: RequestUpload, save_fn_async: SaveFnAsync
    ) -> None:
        try:
            async with self._async_concurrency_limiter:
                deduped = await save_fn_async(
                    lambda _, t: self._stats.update_uploaded_file(event.path, t)
                )
        except Exception:
            self._stats.update_failed_file(event.save_name)
            raise
        finally:
            if event.copied and os.path.isfile(event.path):
                os.remove(event.path)

        self._file_stream.push_success(event.artifact_id, event.save_name)  # type: ignore
        if deduped:
            self._stats.set_file_deduped(event.save_name)

    def _init_artifact(self, artifact_id: str) -> None:
        self._artifacts[artifact_id] = {
            "finalize": False,
            "pending_count": 0,
            "commit_requested": False,
            "pre_commit_callbacks": set(),
            "result_futures": set(),
        }

    def _maybe_commit_artifact(self, artifact_id: str) -> None:
        artifact_status = self._artifacts[artifact_id]
        if (
            artifact_status["pending_count"] == 0
            and artifact_status["commit_requested"]
        ):
            try:
                for pre_callback in artifact_status["pre_commit_callbacks"]:
                    pre_callback()
                if artifact_status["finalize"]:
                    self._api.commit_artifact(artifact_id)
            except Exception as exc:
                termerror(
                    f"Committing artifact failed. Artifact {artifact_id} won't be finalized."
                )
                termerror(str(exc))
                self._fail_artifact_futures(artifact_id, exc)
            else:
                self._resolve_artifact_futures(artifact_id)

    def _fail_artifact_futures(self, artifact_id: str, exc: BaseException) -> None:
        futures = self._artifacts[artifact_id]["result_futures"]
        for result_fut in futures:
            result_fut.set_exception(exc)
        futures.clear()

    def _resolve_artifact_futures(self, artifact_id: str) -> None:
        futures = self._artifacts[artifact_id]["result_futures"]
        for result_fut in futures:
            result_fut.set_result(None)
        futures.clear()

    def start(self) -> None:
        self._thread.start()
        self._loop_thread.start()

    def is_alive(self) -> bool:
        return self._thread.is_alive()
