"""Batching file prepare requests to our API."""

import queue
import sys
import threading
from typing import (
    Any,
    Callable,
    MutableMapping,
    MutableSequence,
    MutableSet,
    NamedTuple,
    Optional,
    TYPE_CHECKING,
    Union,
)

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
        post_commit_callbacks: MutableSet["PostCommitFn"]


PreCommitFn = Callable[[], None]
PostCommitFn = Callable[[], None]
OnRequestFinishFn = Callable[[], None]
SaveFn = Callable[["progress.ProgressFn"], Any]


class RequestUpload(NamedTuple):
    path: str
    save_name: "dir_watcher.SaveName"
    artifact_id: Optional[str]
    md5: Optional[str]
    copied: bool
    save_fn: Optional[SaveFn]
    digest: Optional[str]


class RequestCommitArtifact(NamedTuple):
    artifact_id: str
    finalize: bool
    before_commit: Optional[PreCommitFn]
    on_commit: Optional[PostCommitFn]


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
        self._max_jobs = max_jobs
        self._file_stream = file_stream

        self._thread = threading.Thread(target=self._thread_body)
        self._thread.daemon = True

        # Indexed by files' `save_name`'s, which are their ID's in the Run.
        self._running_jobs: MutableMapping[
            dir_watcher.SaveName, upload_job.UploadJob
        ] = {}
        self._pending_jobs: MutableSequence[RequestUpload] = []

        self._artifacts: MutableMapping[str, "ArtifactStatus"] = {}

        self._finished = False
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
        # are invalid. Mark that we're done, which is used to tell the last
        # upload job that it is last.
        self._finished = True

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
            job.join()
            if job.artifact_id:
                if event.success:
                    self._artifacts[job.artifact_id]["pending_count"] -= 1
                    self._maybe_commit_artifact(job.artifact_id)
                else:
                    termerror(
                        "Uploading artifact file failed. Artifact won't be committed."
                    )
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
            if event.before_commit:
                self._artifacts[event.artifact_id]["pre_commit_callbacks"].add(
                    event.before_commit
                )
            if event.on_commit:
                self._artifacts[event.artifact_id]["post_commit_callbacks"].add(
                    event.on_commit
                )
            self._maybe_commit_artifact(event.artifact_id)
        elif isinstance(event, RequestUpload):
            if event.artifact_id is not None:
                if event.artifact_id not in self._artifacts:
                    self._init_artifact(event.artifact_id)
                self._artifacts[event.artifact_id]["pending_count"] += 1
            if len(self._running_jobs) == self._max_jobs:
                self._pending_jobs.append(event)
            else:
                self._start_upload_job(event)
        else:
            raise Exception("Programming error: unhandled event: %s" % str(event))

    def _start_upload_job(self, event: Event) -> None:
        if not isinstance(event, RequestUpload):
            raise Exception("Programming error: invalid event")

        # Operations on a single backend file must be serialized. if
        # we're already uploading this file, put the event on the
        # end of the queue
        if event.save_name in self._running_jobs:
            self._pending_jobs.append(event)
            return

        # Start it.
        job = upload_job.UploadJob(
            self._event_queue,
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
        self._running_jobs[event.save_name] = job
        job.start()

    def _init_artifact(self, artifact_id: str) -> None:
        self._artifacts[artifact_id] = {
            "finalize": False,
            "pending_count": 0,
            "commit_requested": False,
            "pre_commit_callbacks": set(),
            "post_commit_callbacks": set(),
        }

    def _maybe_commit_artifact(self, artifact_id: str) -> None:
        artifact_status = self._artifacts[artifact_id]
        if (
            artifact_status["pending_count"] == 0
            and artifact_status["commit_requested"]
        ):
            for callback in artifact_status["pre_commit_callbacks"]:
                callback()
            if artifact_status["finalize"]:
                self._api.commit_artifact(artifact_id)
            for callback in artifact_status["post_commit_callbacks"]:
                callback()

    def start(self) -> None:
        self._thread.start()

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def finish(self) -> None:
        self._finished = True

    def shutdown(self) -> None:
        self.finish()
        self._thread.join()
