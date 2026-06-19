"""Helpers for downloading files through the wandb-core sidecar.

A download runs on wandb-core's file transfer worker pool: a start request
returns immediately with a request id, then the status is polled until the
download finishes. Progress is rendered with the same operation-stats display
shown when a run uploads its history and files on finish.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
from typing import TYPE_CHECKING

from wandb.proto.wandb_api_pb2 import (
    ApiRequest,
    FileDownloadStatusRequest,
    StartFileDownloadRequest,
)
from wandb.sdk import wandb_setup
from wandb.sdk.lib import asyncio_compat
from wandb.sdk.lib.printer import new_printer
from wandb.sdk.lib.progress import progress_printer
from wandb.sdk.lib.service.service_connection import WandbApiFailedError

if TYPE_CHECKING:
    from wandb.apis.public.service_api import ServiceApi

# How often to poll the download's status while showing progress.
_POLL_WAIT_SECONDS = 0.5
# How often to repaint progress; also the poll cadence when no progress is shown.
_TICK_SECONDS = 0.1


def download_file(
    service_api: ServiceApi,
    *,
    path: str,
    url: str,
    size: int = 0,
    progress_text: str | None = None,
) -> None:
    """Download a file from a URL to a local path, blocking until it finishes.

    Args:
        service_api: The service API used to reach wandb-core.
        path: The local path to write the file to.
        url: The URL to download the file from.
        size: The expected file size in bytes if known, used for progress.
        progress_text: If set, a progress display with this label is shown
            while the download runs, like the bars shown when a run finishes.

    Raises:
        WandbApiFailedError: The download failed for any reason, including
            transport errors and non-successful HTTP status codes.
    """
    request_id = _start_download(service_api, path=path, url=url, size=size)

    if progress_text is None:
        _wait_for_download(service_api, request_id)
    else:
        wandb_setup.singleton().asyncer.run(
            lambda: _wait_for_download_with_progress(
                service_api, request_id, progress_text
            )
        )


def download_file_into_memory(
    service_api: ServiceApi, *, url: str, size: int = 0
) -> bytes:
    """Download a file through wandb-core and return its contents."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "download")
        download_file(service_api, path=path, url=url, size=size)
        with open(path, "rb") as f:
            return f.read()


def _start_download(service_api: ServiceApi, *, path: str, url: str, size: int) -> int:
    response = service_api.send_api_request(
        ApiRequest(
            start_file_download_request=StartFileDownloadRequest(
                path=path, url=url, size=size
            )
        )
    )
    return response.start_file_download_response.request_id


def _status_request(request_id: int) -> ApiRequest:
    return ApiRequest(
        file_download_status_request=FileDownloadStatusRequest(request_id=request_id)
    )


def _wait_for_download(service_api: ServiceApi, request_id: int) -> None:
    """Poll until the download finishes, without showing progress."""
    while True:
        status = service_api.send_api_request(
            _status_request(request_id)
        ).file_download_status_response
        if status.done:
            if status.error:
                raise WandbApiFailedError(status.error)
            return
        time.sleep(_TICK_SECONDS)


async def _wait_for_download_with_progress(
    service_api: ServiceApi, request_id: int, progress_text: str
) -> None:
    """Poll until the download finishes, rendering run-finish-style progress.

    A poll loop refreshes the operation stats every ``_POLL_WAIT_SECONDS`` while
    a render loop repaints them every ``_TICK_SECONDS``, mirroring the decoupled
    progress display used when a run finishes.
    """
    done = asyncio.Event()
    error: WandbApiFailedError | None = None
    stats = None

    async def poll() -> None:
        nonlocal error, stats
        while True:
            start_time = time.monotonic()
            handle = await service_api.send_api_request_async(
                _status_request(request_id)
            )
            status = (
                await handle.wait_async(timeout=None)
            ).file_download_status_response

            if status.done:
                if status.error:
                    error = WandbApiFailedError(status.error)
                done.set()
                return

            stats = status.operation_stats
            elapsed = time.monotonic() - start_time
            if elapsed < _POLL_WAIT_SECONDS:
                await asyncio_compat.race(
                    asyncio.sleep(_POLL_WAIT_SECONDS - elapsed),
                    done.wait(),
                )

    async def render() -> None:
        with progress_printer(new_printer(), progress_text) as progress:
            while not done.is_set():
                if stats is not None:
                    progress.update(stats)
                await asyncio_compat.race(asyncio.sleep(_TICK_SECONDS), done.wait())

    async with asyncio_compat.open_task_group() as group:
        group.start_soon(poll())
        group.start_soon(render())

    if error is not None:
        raise error
