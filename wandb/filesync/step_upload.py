"""Batching file prepare requests to our API."""

import concurrent.futures
import logging
import queue
import sys
import threading
from typing import (
    TYPE_CHECKING,
    Callable,
    MutableMapping,
    MutableSequence,
    MutableSet,
    NamedTuple,
    Optional,
    Union,
)

from wandb.errors.term import termerror
from wandb.filesync import upload_job
from wandb.sdk.lib.paths import LogicalPath

if TYPE_CHECKING:
    from typing import TypedDict

    from wandb.filesync import stats
    from wandb.sdk.internal import file_stream, internal_api, progress
    from wandb.sdk.internal.settings_static import SettingsStatic

    class ArtifactStatus(TypedDict):
        finalize: bool
        pending_count: int
        commit_requested: bool
        pre_commit_callbacks: MutableSet["PreCommitFn"]
        result_futures: MutableSet["concurrent.futures.Future[None]"]


PreCommitFn = Callable[[], None]
OnRequestFinishFn = Callable[[], None]
SaveFn = Callable[["progress.ProgressFn"], bool]

logger = logging.getLogger(__name__)


class RequestUpload(NamedTuple):
    path: str
    save_name: LogicalPath
    artifact_id: Optional[str]
    md5: Optional[str]
    copied: bool
    save_fn: Optional[SaveFn]
    digest: Optional[str]


class RequestCommitArtifact(NamedTuple):
    artifact_id: str
    finalize: bool
    before_commit: PreCommitFn
    result_future: "concurrent.futures.Future[None]"


class RequestFinish(NamedTuple):
    callback: Optional[OnRequestFinishFn]


class EventJobDone(NamedTuple):
    job: RequestUpload
    exc: Optional[BaseException]


Event = Union[RequestUpload, RequestCommitArtifact, RequestFinish, EventJobDone]


class StepUpload:
    def __init__(
        self,
        api: "internal_api.Api",
        stats: "stats.Stats",
        event_queue: "queue.Queue[Event]",
        max_threads: int,
        file_stream: "file_stream.FileStreamApi",
        settings: Optional["SettingsStatic"] = None,
    ) -> None:
        self._api = api
        self._stats = stats
        self._event_queue = event_queue
        self._file_stream = file_stream

        self._thread = threading.Thread(target=self._thread_body)
        self._thread.daemon = True

        self._pool = concurrent.futures.ThreadPoolExecutor(
            thread_name_prefix="wandb-upload",
            max_workers=max_threads,
        )

        # Indexed by files' `save_name`'s, which are their ID's in the Run.
        self._running_jobs: MutableMapping[LogicalPath, RequestUpload] = {}
        self._pending_jobs: MutableSequence[RequestUpload] = []

        self._artifacts: MutableMapping[str, ArtifactStatus] = {}

        self.silent = bool(settings.silent) if settings else False

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
                self._pool.shutdown(wait=False)
                if finish_callback:
                    finish_callback()
                break

    def _handle_event(self, event: Event) -> None:
        if isinstance(event, EventJobDone):
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
            self._artifacts[event.artifact_id]["result_futures"].add(
                event.result_future
            )
            self._maybe_commit_artifact(event.artifact_id)
        elif isinstance(event, RequestUpload):
            if event.artifact_id is not None:
                if event.artifact_id not in self._artifacts:
                    self._init_artifact(event.artifact_id)
                self._artifacts[event.artifact_id]["pending_count"] += 1
            self._start_upload_job(event)
        else:
            raise TypeError(f"Event has unexpected type: {event!s}")

    def _start_upload_job(self, event: RequestUpload) -> None:
        # Operations on a single backend file must be serialized. if
        # we're already uploading this file, put the event on the
        # end of the queue
        if event.save_name in self._running_jobs:
            self._pending_jobs.append(event)
            return

        self._spawn_upload(event)

    def _spawn_upload(self, event: RequestUpload) -> None:
        """Spawn an upload job, and handles the bookkeeping of `self._running_jobs`.

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
                self._do_upload(event)
            finally:
                self._event_queue.put(EventJobDone(event, exc=sys.exc_info()[1]))

        self._pool.submit(run_and_notify)

    def _do_upload(self, event: RequestUpload) -> None:
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
        for result_future in futures:
            result_future.set_exception(exc)
        futures.clear()

    def _resolve_artifact_futures(self, artifact_id: str) -> None:
        futures = self._artifacts[artifact_id]["result_futures"]
        for result_future in futures:
            result_future.set_result(None)
        futures.clear()

    def start(self) -> None:
        self._thread.start()

    def is_alive(self) -> bool:
        return self._thread.is_alive()
