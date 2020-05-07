"""Batching file prepare requests to our API."""

import multiprocessing
import multiprocessing.pool
import collections
import os
import queue
import shutil
import threading
import time
from six.moves import queue
import wandb.util

from wandb.filesync import step_upload


RequestUpload = collections.namedtuple(
    'RequestUpload', ('path', 'save_name', 'artifact_id', 'copy', 'save_fn', 'digest'))
RequestCommitArtifact = collections.namedtuple(
    'RequestCommitArtifact', ('artifact_id', ))
RequestFinish = collections.namedtuple('RequestFinish', ())

    
class StepChecksum(object):
    def __init__(self, api, tempdir, request_queue, output_queue):
        self._api = api
        self._tempdir = tempdir
        self._request_queue = request_queue
        self._output_queue = output_queue

        self._thread = threading.Thread(target=self._thread_body)
        self._thread.daemon = True

    def _thread_body(self):
        finished = False
        while True:
            req = self._request_queue.get()
            if isinstance(req, RequestUpload):
                path = req.path
                if req.copy:
                    path = os.path.join(self._tempdir.name, '%s-%s' % (
                        wandb.util.generate_id(), req.save_name))
                    wandb.util.mkdir_exists_ok(os.path.dirname(path))
                    shutil.copy2(req.path, path)
                checksum = wandb.util.md5_file(path)
                self._output_queue.put(
                    step_upload.RequestUpload(
                        path, req.save_name, req.artifact_id, checksum, req.copy,
                        req.save_fn, req.digest))
            elif isinstance(req, RequestCommitArtifact):
                self._output_queue.put(step_upload.RequestCommitArtifact(req.artifact_id))
            elif isinstance(req, RequestFinish):
                break
            else:
                raise Exception('internal error')

        self._output_queue.put(step_upload.RequestFinish())

    def start(self):
        self._thread.start()

    def is_alive(self):
        return self._thread.is_alive()

    def finish(self):
        self._request_queue.put(RequestFinish())