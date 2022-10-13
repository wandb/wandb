"""Batching file prepare requests to our API."""

import asyncio
import queue
import sys
import threading
import time
from typing import (
    TYPE_CHECKING,
    List,
    Mapping,
    NamedTuple,
    Optional,
    Sequence,
    Tuple,
    Union,
)
import wandb

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
            upload_url: Optional[str],  # GraphQL type File.uploadUrl
            upload_headers: Sequence[str],  # GraphQL type File.uploadHeaders
            artifact_id: str,  # GraphQL type File.artifact.id
        ) -> None:
            pass


# Request for a file to be prepared.
class RequestPrepare(NamedTuple):
    prepare_fn: "DoPrepareFn"
    on_prepare: Optional["OnPrepareFn"]
    response: "asyncio.Future[ResponsePrepare]"


class RequestFinish(NamedTuple):
    pass


class ResponsePrepare(NamedTuple):
    upload_url: Optional[str]
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
            wandb.termlog(f"SRP: PrepareRequest: got {request}")
            if isinstance(request, RequestFinish):
                break
            finish, batch = self._gather_batch(request)
            prepare_response = self._prepare_batch(batch)
            # send responses
            for prepare_request in batch:
              try:
                wandb.termlog(f"SRP: PrepareRequest: for {request}: gonna respond to {prepare_request.prepare_fn()}")
                name = prepare_request.prepare_fn()["name"]
                response_file = prepare_response[name]
                upload_url = response_file["uploadUrl"]
                upload_headers = response_file["uploadHeaders"]
                birth_artifact_id = response_file["artifact"]["id"]
                if prepare_request.on_prepare:
                    prepare_request.on_prepare(
                        upload_url, upload_headers, birth_artifact_id
                    )
                def _respond(request=request, prepare_request=prepare_request, upload_url=upload_url,upload_headers=upload_headers,birth_artifact_id=birth_artifact_id):
                    wandb.termlog(f"SRP: PrepareRequest: setting future-result")
                    prepare_request.response.set_result(
                        ResponsePrepare(upload_url, upload_headers, birth_artifact_id)
                    )
                    wandb.termlog(f"SRP: PrepareRequest: for {request}: responded to {prepare_request.prepare_fn()}")
                prepare_request.response.get_loop().call_soon_threadsafe(_respond)
              except Exception as e:
                wandb.termlog(f"SRP: PrepareRequest: for {request}: failed to respond to {prepare_request.prepare_fn()}: {e}")
                raise
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
    ) -> Mapping[str, "internal_api.CreateArtifactFilesResponseFile"]:
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

    async def prepare(self, prepare_fn: "DoPrepareFn") -> ResponsePrepare:
        wandb.termlog(f"SRP: prepare({prepare_fn()})")
        response = asyncio.Future()
        self._request_queue.put(RequestPrepare(prepare_fn, None, response))
        wandb.termlog(f"SRP: prepare({prepare_fn()}): about to await")
        res = await response
        wandb.termlog(f"SRP: prepare({prepare_fn()}): done awaiting: {res}")
        return res

    def start(self) -> None:
        self._thread.start()

    def finish(self) -> None:
        self._request_queue.put(RequestFinish())

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def shutdown(self) -> None:
        self.finish()
        self._thread.join()
