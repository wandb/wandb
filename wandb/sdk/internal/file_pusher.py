import logging
import os
import queue
import tempfile
import time

import wandb
import wandb.util

from wandb.filesync import stats
from wandb.filesync import step_checksum
from wandb.filesync import step_upload


# Temporary directory for copies we make of some file types to
# reduce the probability that the file gets changed while we're
# uploading it.
TMP_DIR = tempfile.TemporaryDirectory("wandb")


logger = logging.getLogger(__name__)


class FilePusher:
    """Parallel file upload class.
    This manages uploading multiple files in parallel. It will restart a given file's
    upload job if it receives a notification that that file has been modified.
    The finish() method will block until all events have been processed and all
    uploads are complete.
    """

    MAX_UPLOAD_JOBS = 64

    def __init__(self, api, file_stream, silent=False):
        self._api = api

        self._tempdir = tempfile.TemporaryDirectory("wandb")

        self._stats = stats.Stats()

        self._incoming_queue = queue.Queue()
        self._event_queue = queue.Queue()

        self._step_checksum = step_checksum.StepChecksum(
            self._api,
            self._tempdir,
            self._incoming_queue,
            self._event_queue,
            self._stats,
        )
        self._step_checksum.start()

        self._step_upload = step_upload.StepUpload(
            self._api,
            self._stats,
            self._event_queue,
            self.MAX_UPLOAD_JOBS,
            file_stream=file_stream,
            silent=silent,
        )
        self._step_upload.start()

    def get_status(self):
        running = self.is_alive()
        summary = self._stats.summary()
        return running, summary

    def print_status(self, prefix=True):
        step = 0
        spinner_states = ["-", "\\", "|", "/"]
        stop = False
        while True:
            if not self.is_alive():
                stop = True
            summary = self._stats.summary()
            line = " {:.2f}MB of {:.2f}MB uploaded ({:.2f}MB deduped)\r".format(
                summary["uploaded_bytes"] / 1048576.0,
                summary["total_bytes"] / 1048576.0,
                summary["deduped_bytes"] / 1048576.0,
            )
            line = spinner_states[step % 4] + line
            step += 1
            wandb.termlog(line, newline=False, prefix=prefix)
            if stop:
                break
            time.sleep(0.25)
        dedupe_fraction = (
            summary["deduped_bytes"] / float(summary["total_bytes"])
            if summary["total_bytes"] > 0
            else 0
        )
        if dedupe_fraction > 0.01:
            wandb.termlog(
                "W&B sync reduced upload amount by %.1f%%             "
                % (dedupe_fraction * 100),
                prefix=prefix,
            )
        # clear progress line.
        wandb.termlog(" " * 79, prefix=prefix)

    def file_counts_by_category(self):
        return self._stats.file_counts_by_category()

    def file_changed(
        self,
        save_name,
        path,
        artifact_id=None,
        copy=True,
        use_prepare_flow=False,
        save_fn=None,
        digest=None,
    ):
        """Tell the file pusher that a file's changed and should be uploaded.
        Arguments:
            save_name: string logical location of the file relative to the run
                directory.
            path: actual string path of the file to upload on the filesystem.
        """
        # Tests in linux were failing because wandb-events.jsonl didn't exist
        if not os.path.exists(path) or not os.path.isfile(path):
            return
        if os.path.getsize(path) == 0:
            return

        save_name = wandb.util.to_forward_slash_path(save_name)
        event = step_checksum.RequestUpload(
            path, save_name, artifact_id, copy, use_prepare_flow, save_fn, digest
        )
        self._incoming_queue.put(event)

    def store_manifest_files(self, manifest, artifact_id, save_fn):
        event = step_checksum.RequestStoreManifestFiles(manifest, artifact_id, save_fn)
        self._incoming_queue.put(event)

    def commit_artifact(
        self, artifact_id, finalize=True, before_commit=None, on_commit=None
    ):
        event = step_checksum.RequestCommitArtifact(
            artifact_id, finalize, before_commit, on_commit
        )
        self._incoming_queue.put(event)

    def finish(self, callback=None):
        logger.info("shutting down file pusher")
        self._incoming_queue.put(step_checksum.RequestFinish(callback))

    def join(self):
        # NOTE: must have called finish before join
        logger.info("waiting for file pusher")
        while self.is_alive():
            time.sleep(0.5)

    def is_alive(self):
        return self._step_checksum.is_alive() or self._step_upload.is_alive()
