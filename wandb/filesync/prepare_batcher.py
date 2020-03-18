"""Batching file prepare requests to our API."""

import collections
import queue
import threading
import time
from six.moves import queue

# Request for a file to be prepared.
RequestPrepare = collections.namedtuple(
    'RequestPrepare', ('path', 'save_name', 'md5', 'artifact_id', 'response_queue'))

RequestFinish = collections.namedtuple('RequestPrepare', ())

    
class PrepareBatcher(object):
    """A thread that batches requests to our file prepare API.

    Any number of threads may call prepare_async() in parallel. The PrepareBatcher thread
    will batch requests up and send them all to the backend at once.
    """

    def __init__(self, api, batch_time):
        self._api = api
        self._batch_time = batch_time
        self._request_queue = queue.Queue()
        self._thread = threading.Thread(target=self._thread_body)

    def _thread_body(self):
        finish = False
        while True:
            request = self._request_queue.get()
            print('Got initial request', request)
            if isinstance(request, RequestFinish):
                break
            finish, batch = self._gather_batch(request)
            print('Got batch', finish, batch)
            prepare_response = self._prepare_batch(batch)
            # send responses
            for prepare_request in batch:
                response_file = prepare_response[prepare_request.save_name]
                prepare_request.response_queue.put(response_file['uploadUrl'])
            if finish:
                break
            
    def _gather_batch(self, first_request):
        batch_start_time = time.time()
        batch = [first_request]
        while True:
            remaining_time = self._batch_time - (time.time() - batch_start_time)
            print('Remaining time', remaining_time)
            try:
                request = self._request_queue.get(block=True, timeout=remaining_time)
                if isinstance(request, RequestFinish):
                    return True, batch
                batch.append(request)
            except queue.Empty:
                break
        return False, batch

    def _prepare_batch(self, batch):
        """Execute the prepareFiles API call.

        Args:
            batch: List of RequestPrepare objects
        Returns:
            dict of (save_name: ResponseFile) pairs where ResponseFile is a dict with
                an uploadUrl key. The value of the uploadUrl key is None if the file
                already exists, or a url string if the file should be uploaded.
        """
        file_specs = []
        for prepare_request in batch:
            file_specs.append({
                'name': prepare_request.save_name,
                'artifactVersionID': prepare_request.artifact_id,
                'fingerprint': prepare_request.md5})
        return self._api.prepare_files(file_specs)

    def prepare_async(self, path, save_name, md5, artifact_id):
        """Request the backend to prepare a file for upload.
        
        Returns:
            response_queue: a queue containing the prepare result. The prepare result is
                either a file upload url, or None if the file doesn't need to be uploaded.
        """
        response_queue = queue.Queue()
        self._request_queue.put(RequestPrepare(path, save_name, md5, artifact_id, response_queue))
        return response_queue

    def prepare(self, path, save_name, md5, artifact_id):
        return self.prepare_async(path, save_name, md5, artifact_id).get()

    def start(self):
        self._thread.start()

    def finish(self):
        self._request_queue.put(RequestFinish())

    def shutdown(self):
        self.finish()
        self._thread.join()
