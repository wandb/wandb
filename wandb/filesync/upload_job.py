import collections
import os
import threading

import wandb
from wandb import util

EventJobDone = collections.namedtuple('EventJobDone', ('job'))

class UploadJob(threading.Thread):
    def __init__(self, step_prepare, done_queue, stats, api, save_name, path, artifact_id, md5, copied, save_fn, digest):
        """A file upload thread.

        Arguments:
            done_queue: queue.Queue in which to put an EventJobDone event when
                the upload finishes.
            push_function: function(save_name, actual_path) which actually uploads
                the file.
            save_name: string logical location of the file relative to the run
                directory.
            path: actual string path of the file to upload on the filesystem.
        """
        self._step_prepare = step_prepare
        self._done_queue = done_queue
        self._stats = stats
        self._api = api
        self.save_name = save_name
        self.save_path = self.path = path
        self.artifact_id = artifact_id
        self.md5 = md5
        self.copied = copied
        self.save_fn = save_fn
        self.digest = digest
        super(UploadJob, self).__init__()

    def run(self):
        try:
            self.push()
        finally:
            if self.copied and os.path.isfile(self.save_path):
                os.remove(self.save_path)
            self._done_queue.put(EventJobDone(self))

    def push(self):
        try:
            size = os.path.getsize(self.save_path)
        except OSError:
            size = 0

        if self.save_fn:
            # TODO: this needs to retry
            # TODO: track metrics
            self.save_fn(self.save_path, self.digest, self._api)
            return

        prepare_response = self._step_prepare.prepare(
            self.save_path, self.save_name, self.md5, self.artifact_id)
        if prepare_response.upload_url == None:
            self._stats.add_deduped_file(self.save_name, size)
        else:
            self._stats.add_uploaded_file(self.save_name, size)
            upload_url = prepare_response.upload_url
            upload_headers = prepare_response.upload_headers

            extra_headers = {}
            for upload_header in upload_headers:
                key, val = upload_header.split(':', 1)
                extra_headers[key] = val
            # Copied from push TODO(artifacts): clean up
            # If the upload URL is relative, fill it in with the base URL,
            # since its a proxied file store like the on-prem VM.
            if upload_url.startswith('/'):
                upload_url = '{}{}'.format(self._api.api_url, upload_url)
            try:
                with open(self.save_path, 'rb') as f:
                    self._api.upload_file_retry(
                        upload_url,
                        f,
                        lambda _, t: self.progress(t),
                        extra_headers=extra_headers)
            except Exception as e:
                self._stats.update_failed_file(self.save_name)
                wandb.util.sentry_exc(e)
                wandb.termerror('Error uploading "{}": {}, {}'.format(
                    self.save_name, type(e).__name__, e))

    def progress(self, total_bytes):
        self._stats.update_uploaded_file(self.save_name, total_bytes)

