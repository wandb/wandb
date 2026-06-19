import pytest
from wandb.apis.public import _download
from wandb.proto import wandb_api_pb2 as apb
from wandb.sdk.lib import asyncio_compat
from wandb.sdk.lib.service.service_connection import WandbApiFailedError


def _start_response(request_id: int) -> apb.ApiResponse:
    return apb.ApiResponse(
        start_file_download_response=apb.StartFileDownloadResponse(
            request_id=request_id
        )
    )


def _done_response(error: str = "") -> apb.ApiResponse:
    return apb.ApiResponse(
        file_download_status_response=apb.FileDownloadStatusResponse(
            done=True, error=error
        )
    )


# --- synchronous (no-progress) path ---


class _FakeServiceApi:
    """A service API stub that records requests and replies via a handler."""

    def __init__(self, handler):
        self._handler = handler
        self.requests: list[apb.ApiRequest] = []

    def send_api_request(self, request, timeout=None):
        self.requests.append(request)
        return self._handler(request)


def test_download_file_starts_then_polls_status():
    def handler(request: apb.ApiRequest) -> apb.ApiResponse:
        if request.WhichOneof("request") == "start_file_download_request":
            return _start_response(7)
        return _done_response()

    api = _FakeServiceApi(handler)
    _download.download_file(
        api, path="/tmp/model.bin", url="https://files.example/model.bin", size=42
    )

    start = api.requests[0].start_file_download_request
    assert start.path == "/tmp/model.bin"
    assert start.url == "https://files.example/model.bin"
    assert start.size == 42
    assert api.requests[1].file_download_status_request.request_id == 7


def test_download_file_raises_on_status_error():
    def handler(request: apb.ApiRequest) -> apb.ApiResponse:
        if request.WhichOneof("request") == "start_file_download_request":
            return _start_response(1)
        return _done_response(error="failed to download: status: 404 Not Found")

    api = _FakeServiceApi(handler)
    with pytest.raises(WandbApiFailedError, match="404 Not Found"):
        _download.download_file(
            api, path="/tmp/model.bin", url="https://files.example/model.bin"
        )


def test_download_file_into_memory_returns_contents():
    def handler(request: apb.ApiRequest) -> apb.ApiResponse:
        if request.WhichOneof("request") == "start_file_download_request":
            # Simulate wandb-core writing the file before completion.
            with open(request.start_file_download_request.path, "wb") as f:
                f.write(b'{"ok":true}')
            return _start_response(3)
        return _done_response()

    api = _FakeServiceApi(handler)
    contents = _download.download_file_into_memory(
        api, url="https://files.example/wandb-metadata.json", size=11
    )
    assert contents == b'{"ok":true}'


# --- async (progress) watcher ---


class _FakeAsyncServiceApi:
    """A service API stub whose status polls resolve asynchronously."""

    def __init__(self, status_response: apb.ApiResponse):
        self._status_response = status_response
        self.requests: list[apb.ApiRequest] = []

    async def send_api_request_async(self, request):
        self.requests.append(request)
        return _FakeHandle(self._status_response)


class _FakeHandle:
    def __init__(self, response: apb.ApiResponse):
        self._response = response

    async def wait_async(self, timeout=None):
        return self._response


def test_progress_watcher_completes():
    api = _FakeAsyncServiceApi(_done_response())

    asyncio_compat.run(
        lambda: _download._wait_for_download_with_progress(api, 5, "downloading x")
    )

    assert api.requests[0].file_download_status_request.request_id == 5


def test_progress_watcher_raises_on_error():
    api = _FakeAsyncServiceApi(_done_response(error="boom: 404 Not Found"))

    with pytest.raises(WandbApiFailedError, match="404 Not Found"):
        asyncio_compat.run(
            lambda: _download._wait_for_download_with_progress(api, 5, "downloading x")
        )
