"""Batching file prepare requests to our API."""

import collections
import queue
import threading
import time

# Request for a file to be prepared.
RequestPrepare = collections.namedtuple(
    "RequestPrepare", ("prepare_fn", "on_prepare", "response_queue")
)

RequestFinish = collections.namedtuple("RequestFinish", ())

ResponsePrepare = collections.namedtuple(
    "ResponsePrepare", ("upload_url", "upload_headers", "birth_artifact_id")
)


class StepPrepare:
    """A thread that batches requests to our file prepare API.

    Any number of threads may call prepare_async() in parallel. The PrepareBatcher thread
    will batch requests up and send them all to the backend at once.
    """

    def __init__(self, api, batch_time, inter_event_time, max_batch_size):
        self._api = api
        self._inter_event_time = inter_event_time
        self._batch_time = batch_time
        self._max_batch_size = max_batch_size
        self._request_queue = queue.Queue()
        self._thread = threading.Thread(target=self._thread_body)
        self._thread.daemon = True

    def _thread_body(self):
        while True:
            request = self._request_queue.get()
            if isinstance(request, RequestFinish):
                break
            finish, batch = self._gather_batch(request)
            prepare_response = self._prepare_batch(batch)
            # send responses
            for prepare_request in batch:
                name = prepare_request.prepare_fn()["name"]
                response_file = prepare_response[name]
                upload_url = response_file["uploadUrl"]
                upload_headers = response_file["uploadHeaders"]
                birth_artifact_id = response_file["artifact"]["id"]
                if prepare_request.on_prepare:
                    prepare_request.on_prepare(
                        upload_url, upload_headers, birth_artifact_id
                    )
                prepare_request.response_queue.put(
                    ResponsePrepare(upload_url, upload_headers, birth_artifact_id)
                )
            if finish:
                break

    def _gather_batch(self, first_request):
        batch_start_time = time.time()
        batch = [first_request]
        while True:
            try:
                request = self._request_queue.get(
                    block=True, timeout=self._inter_event_time
                )
                if isinstance(request, RequestFinish):
                    return True, batch
                batch.append(request)
                remaining_time = self._batch_time - (time.time() - batch_start_time)
                if remaining_time < 0 or len(batch) >= self._max_batch_size:
                    break
            except queue.Empty:
                break
        return False, batch

    def _prepare_batch(self, batch):
        """Execute the prepareFiles API call.

        Arguments:
            batch: List of RequestPrepare objects
        Returns:
            dict of (save_name: ResponseFile) pairs where ResponseFile is a dict with
                an uploadUrl key. The value of the uploadUrl key is None if the file
                already exists, or a url string if the file should be uploaded.
        """
        file_specs = []
        for prepare_request in batch:
            file_spec = prepare_request.prepare_fn()
            file_specs.append(file_spec)
        return self._api.create_artifact_files(file_specs)

    def prepare_async(self, prepare_fn, on_prepare=None):
        """Request the backend to prepare a file for upload.

        Returns:
            response_queue: a queue containing the prepare result. The prepare result is
                either a file upload url, or None if the file doesn't need to be uploaded.
        """
        response_queue = queue.Queue()
        self._request_queue.put(RequestPrepare(prepare_fn, on_prepare, response_queue))
        return response_queue

    def prepare(self, prepare_fn):
        return self.prepare_async(prepare_fn).get()

    def start(self):
        self._thread.start()

    def finish(self):
        self._request_queue.put(RequestFinish())

    def is_alive(self):
        return self._thread.is_alive()

    def shutdown(self):
        self.finish()
        self._thread.join()
