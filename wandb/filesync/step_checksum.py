"""Batching file prepare requests to our API."""

import multiprocessing
import multiprocessing.pool
import collections
import queue
import threading
import time
from six.moves import queue
import wandb.util

from wandb.filesync import step_upload


RequestUpload = collections.namedtuple(
    'RequestUpload', ('path', 'save_name', 'artifact_id'))
RequestCommitArtifact = collections.namedtuple(
    'RequestCommitArtifact', ('artifact_id', ))
RequestFinish = collections.namedtuple('RequestFinish', ())

    
class StepChecksum(object):
    def __init__(self, api, batch_time, batch_max_files, request_queue, output_queue):
        self._api = api
        self._batch_time = batch_time
        self._batch_max_files = batch_max_files
        self._request_queue = request_queue
        self._output_queue = output_queue

        self._thread = threading.Thread(target=self._thread_body)
        self._thread.daemon = True

    def _thread_body(self):
        finished = False
        while True:
            # TODO: we're no longer batching these. Remove batching code
            artifact_commits = []
            batch = []
            batch_started_at = time.time()
            batch_end_at = batch_started_at + self._batch_time
            while time.time() < batch_end_at and len(batch) < self._batch_max_files:
                # Get the latest event
                try:
                    wait_secs = batch_end_at - time.time()
                    event = self._request_queue.get(timeout=wait_secs)
                except queue.Empty:
                    # If nothing is available in the batch by the timeout
                    # wrap up and send the current batch immediately.
                    break
                # If it's a finish, stop waiting and send the current batch
                # immediately.
                if isinstance(event, RequestCommitArtifact):
                    artifact_commits.append(event.artifact_id)
                elif isinstance(event, RequestFinish):
                    finished = True
                    break
                elif isinstance(event, RequestUpload):
                    # Otherwise, it's file changed, so add it to the pending batch.
                    batch.append(event)
                else:
                    raise Exception('invalid event %s' % str(event))

            if batch:
                paths = [e.path for e in batch]
                checksums = []
                for path in paths:
                    checksums.append(wandb.util.md5_file(path))

                file_specs = []
                for e, checksum in zip(batch, checksums):
                    self._output_queue.put(
                        step_upload.RequestUpload(e.path, e.save_name, e.artifact_id, checksum))

            # pass artifact commits through to step_upload, only after sending prior
            # upload requests
            for artifact_id in artifact_commits:
                self._output_queue.put(step_upload.RequestCommitArtifact(artifact_id))

            # And stop the infinite loop if we've finished
            if finished:
                self._output_queue.put(step_upload.RequestFinish())
                break

    def start(self):
        self._thread.start()

    def is_alive(self):
        return self._thread.is_alive()

    def finish(self):
        self._request_queue.put(RequestFinish())

    def shutdown(self):
        self.finish()
        self._thread.join()
