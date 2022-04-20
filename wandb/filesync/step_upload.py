"""Batching file prepare requests to our API."""

import collections
import queue
import threading

from wandb.filesync import upload_job
from wandb.errors.term import termerror


RequestUpload = collections.namedtuple(
    "EventStartUploadJob",
    ("path", "save_name", "artifact_id", "md5", "copied", "save_fn", "digest"),
)
RequestCommitArtifact = collections.namedtuple(
    "RequestCommitArtifact", ("artifact_id", "finalize", "before_commit", "on_commit")
)
RequestFinish = collections.namedtuple("RequestFinish", ("callback"))


class StepUpload:
    def __init__(self, api, stats, event_queue, max_jobs, file_stream, silent=False):
        self._api = api
        self._stats = stats
        self._event_queue = event_queue
        self._max_jobs = max_jobs
        self._file_stream = file_stream

        self._thread = threading.Thread(target=self._thread_body)
        self._thread.daemon = True

        # Indexed by files' `save_name`'s, which are their ID's in the Run.
        self._running_jobs = {}
        self._pending_jobs = []

        self._artifacts = {}

        self._finished = False
        self.silent = silent

    def _thread_body(self):
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

    def _handle_event(self, event):
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

    def _start_upload_job(self, event):
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

    def _init_artifact(self, artifact_id):
        self._artifacts[artifact_id] = {
            "pending_count": 0,
            "commit_requested": False,
            "pre_commit_callbacks": set(),
            "post_commit_callbacks": set(),
        }

    def _maybe_commit_artifact(self, artifact_id):
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

    def start(self):
        self._thread.start()

    def is_alive(self):
        return self._thread.is_alive()

    def shutdown(self):
        self.finish()
        self._thread.join()
