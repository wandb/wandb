"""Batching file prepare requests to our API."""

import queue
import sys
import threading
import time
from typing import (
    Any,
    Callable,
    List,
    Mapping,
    NamedTuple,
    Optional,
    Sequence,
    Tuple,
    TYPE_CHECKING,
    Union,
)

if TYPE_CHECKING:
    from wandb.sdk.internal import internal_api

    if sys.version_info >= (3, 8):
        from typing import Protocol
    else:
        from typing_extensions import Protocol

    class DoPrepareFn(Protocol):
        def __call__(self) -> "internal_api.CreateArtifactFileSpecInput":
            pass

    class OnPrepareFn(Protocol):
        def __call__(
            self,
            upload_url: str,  # GraphQL type File.uploadUrl
            upload_headers: Sequence[str],  # GraphQL type File.uploadHeaders
            artifact_id: str,  # GraphQL type File.artifact.id
        ) -> None:
            pass


# Request for a file to be prepared.
class RequestPrepare(NamedTuple):
    prepare_fn: "DoPrepareFn"
    on_prepare: Optional["OnPrepareFn"]
    response_queue: "queue.Queue[ResponsePrepare]"


class RequestFinish(NamedTuple):
    pass


class ResponsePrepare(NamedTuple):
    upload_url: str
    upload_headers: Sequence[str]
    birth_artifact_id: str


Event = Union[RequestPrepare, RequestFinish, ResponsePrepare]


class StepPrepare:
    """A thread that batches requests to our file prepare API.

    Any number of threads may call prepare_async() in parallel. The PrepareBatcher thread
    will batch requests up and send them all to the backend at once.
    """

    def __init__(
        self,
        api: "internal_api.Api",
        batch_time: float,
        inter_event_time: float,
        max_batch_size: int,
    ) -> None:
        self._api = api
        self._inter_event_time = inter_event_time
        self._batch_time = batch_time
        self._max_batch_size = max_batch_size
        self._request_queue: "queue.Queue[RequestPrepare | RequestFinish]" = (
            queue.Queue()
        )
        self._thread = threading.Thread(target=self._thread_body)
        self._thread.daemon = True

    def _thread_body(self) -> None:
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
                upload_url: str = response_file["uploadUrl"]
                upload_headers: Sequence[str] = response_file["uploadHeaders"]
                birth_artifact_id: str = response_file["artifact"]["id"]
                if prepare_request.on_prepare:
                    prepare_request.on_prepare(
                        upload_url, upload_headers, birth_artifact_id
                    )
                prepare_request.response_queue.put(
                    ResponsePrepare(upload_url, upload_headers, birth_artifact_id)
                )
            if finish:
                break

    def _gather_batch(
        self, first_request: RequestPrepare
    ) -> Tuple[bool, Sequence[RequestPrepare]]:
        batch_start_time = time.time()
        batch: List[RequestPrepare] = [first_request]
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

    def _prepare_batch(
        self, batch: Sequence[RequestPrepare]
    ) -> Mapping[str, Mapping[str, Any]]:
        """Execute the prepareFiles API call.

        Arguments:
            batch: List of RequestPrepare objects
        Returns:
            dict of (save_name: ResponseFile) pairs where ResponseFile is a dict with
                an uploadUrl key. The value of the uploadUrl key is None if the file
                already exists, or a url string if the file should be uploaded.
        """
        file_specs: List["internal_api.CreateArtifactFileSpecInput"] = []
        for prepare_request in batch:
            file_spec = prepare_request.prepare_fn()
            file_specs.append(file_spec)
        return self._api.create_artifact_files(file_specs)

    def prepare_async(
        self, prepare_fn: "DoPrepareFn", on_prepare: Optional[Callable[..., Any]] = None
    ) -> "queue.Queue[ResponsePrepare]":
        """Request the backend to prepare a file for upload.

        Returns:
            response_queue: a queue containing the prepare result. The prepare result is
                either a file upload url, or None if the file doesn't need to be uploaded.
        """
        response_queue: "queue.Queue[ResponsePrepare]" = queue.Queue()
        self._request_queue.put(RequestPrepare(prepare_fn, on_prepare, response_queue))
        return response_queue

    def prepare(self, prepare_fn: "DoPrepareFn") -> ResponsePrepare:
        return self.prepare_async(prepare_fn).get()

    def start(self) -> None:
        self._thread.start()

    def finish(self) -> None:
        self._request_queue.put(RequestFinish())

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def shutdown(self) -> None:
        self.finish()
        self._thread.join()
