"""Batching file prepare requests to our API."""

import asyncio
import queue
import sys
import threading
from typing import (
    TYPE_CHECKING,
    Any,
    Awaitable,
    Callable,
    MutableMapping,
    MutableSequence,
    MutableSet,
    NamedTuple,
    Optional,
    Union,
)

import wandb

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
SaveFn = Callable[["progress.ProgressFn"], Awaitable[bool]]


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
        self._pending_jobs: MutableMapping[
            dir_watcher.SaveName, RequestUpload
        ] = {}
        
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(target=self._loop.run_forever)
        self._loop_thread.daemon = True

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
            # wandb.termlog(f"SRP: StepUpload got event: {event}")
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
                # wandb.termlog(f"SRP: StepUpload got event (post-finish): {event}")
            except queue.Empty:
                event = None
            if event:
                self._handle_event(event)
            elif not self._running_jobs:
                # Queue was empty and no jobs left.
                if finish_callback:
                    finish_callback()

                def stop_loop():
                    wandb.termerror("SRP: StepUpload stopping loop")
                    self._loop.stop()
                self._loop.call_soon_threadsafe(stop_loop)
                break
        # wandb.termlog(f"SRP: UploadJob: terminating")

    def _handle_event(self, event: Event) -> None:
        if isinstance(event, upload_job.EventJobDone):
            job = event.job
            # wandb.termlog(f"SRP: job done: {job.save_name}, artifact {job.artifact_id}, success {event.success}")
            if job.artifact_id:
                if event.success:
                    # wandb.termlog(f"SRP: decreasing pending count for {job.artifact_id} because of {job.save_name} succeeded")
                    self._artifacts[job.artifact_id]["pending_count"] -= 1
                    self._maybe_commit_artifact(job.artifact_id)
                else:
                    termerror(
                        "Uploading artifact file failed. Artifact won't be committed."
                    )
            self._running_jobs.pop(job.save_name)
            if job.save_name in self._pending_jobs:
                self._start_upload_job(self._pending_jobs.pop(job.save_name))
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
            if event.artifact_id and event.save_name not in self._pending_jobs:
                # wandb.termlog(f"SRP: increasing pending count for {event.artifact_id} because of {event.save_name} (inserting into pending)")
                self._artifacts[event.artifact_id]["pending_count"] += 1
            self._pending_jobs[event.save_name] = event
            return

        if event.artifact_id:
            # wandb.termlog(f"SRP: increasing pending count for {event.artifact_id} because of {event.save_name} (running)")
            self._artifacts[event.artifact_id]["pending_count"] += 1

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
        self._loop.call_soon_threadsafe(lambda: self._loop.create_task(job.run()))

    def _init_artifact(self, artifact_id: str) -> None:
        self._artifacts[artifact_id] = {
            "finalize": False,
            "pending_count": 0,
            "commit_requested": False,
            "pre_commit_callbacks": set(),
            "post_commit_callbacks": set(),
        }

    def _maybe_commit_artifact(self, artifact_id: str) -> None:
        # wandb.termlog(f"SRP: maybe_commit_artifact({artifact_id})")
        artifact_status = self._artifacts[artifact_id]
        if (
            artifact_status["pending_count"] == 0
            and artifact_status["commit_requested"]
        ):
            # wandb.termlog(f"SRP: maybe_commit_artifact({artifact_id}): about to precommit")
            for callback in artifact_status["pre_commit_callbacks"]:
                callback()
            if artifact_status["finalize"]:
                # wandb.termlog(f"SRP: maybe_commit_artifact({artifact_id}): about to api.commit")
                self._api.commit_artifact(artifact_id)
                # wandb.termlog(f"SRP: maybe_commit_artifact({artifact_id}): done with api.commit")
            for callback in artifact_status["post_commit_callbacks"]:
                callback()
            # wandb.termlog(f"SRP: maybe_commit_artifact({artifact_id}): done with postcommit")
        else:
            pass # wandb.termlog(f"SRP: maybe_commit_artifact({artifact_id}): never mind, status = {artifact_status}")

    def start(self) -> None:
        self._thread.start()
        self._loop_thread.start()

    def is_alive(self) -> bool:
        return self._thread.is_alive() or self._loop_thread.is_alive()

    def finish(self) -> None:
        self._finished = True

    def shutdown(self) -> None:
        self.finish()
        self._thread.join()
