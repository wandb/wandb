from __future__ import annotations

import asyncio
import pathlib
import time
from dataclasses import dataclass

import wandb.sdk.wandb_setup as wandb_setup
from wandb.apis.public import api as public
from wandb.proto import wandb_api_pb2 as apb
from wandb.sdk.lib import asyncio_compat
from wandb.sdk.lib.printer import new_printer
from wandb.sdk.lib.progress import progress_printer
from wandb.sdk.lib.service.service_connection import WandbApiFailedError

_POLL_WAIT_SECONDS = 0.1


class IncompleteRunHistoryError(Exception):
    """Raised when run history has incomplete history.

    Incomplete history occurs when some data has not been exported to
    parquet files yet, typically because the run is still ongoing.
    """


@dataclass(frozen=True)
class DownloadHistoryResult:
    """Result of downloading a run's history exports.

    Attributes:
        paths: The paths to the downloaded history files.
        errors: A dictionary mapping file paths to error messages for files that
           failed to download. None if all downloads succeeded.
        contains_live_data: Whether the run contains live data,
            not yet exported to parquet files.
    """

    paths: list[pathlib.Path]
    contains_live_data: bool
    errors: dict[pathlib.Path, str] | None = None


def wait_for_download(
    api: public.Api,
    request_id: int,
    contains_live_data: bool,
) -> DownloadHistoryResult:
    return wandb_setup.singleton().asyncer.run(
        lambda: _watch_download_status(
            api=api,
            request_id=request_id,
            contains_live_data=contains_live_data,
        )
    )


async def _watch_download_status(
    api: public.Api,
    request_id: int,
    contains_live_data: bool,
) -> DownloadHistoryResult:
    return await _DownloadStatusWatcher(
        api=api,
        request_id=request_id,
        contains_live_data=contains_live_data,
    ).wait_with_progress()


class _DownloadStatusWatcher:
    def __init__(
        self,
        api: public.Api,
        request_id: int,
        contains_live_data: bool,
    ):
        self.api = api
        self.request_id = request_id
        self.contains_live_data = contains_live_data
        self.done_event = asyncio.Event()
        self.download_result: DownloadHistoryResult | None = None
        self._rate_limit_last_time: float | None = None

    async def wait_with_progress(self) -> DownloadHistoryResult:
        async with asyncio_compat.open_task_group() as group:
            group.start_soon(self._wait_then_mark_done())
            group.start_soon(self._show_progress_until_done())

        if self.download_result is None:
            raise WandbApiFailedError("Failed to get download status")
        return self.download_result

    async def _wait_then_mark_done(self) -> None:
        api_request = apb.ApiRequest(
            read_run_history_request=apb.ReadRunHistoryRequest(
                download_run_history=apb.DownloadRunHistory(
                    request_id=self.request_id,
                )
            )
        )

        handle = await self.api._send_api_request_async(api_request)
        response = await handle.wait_async(timeout=None)

        downloaded_files = [
            pathlib.Path(file_name)
            for file_name in response.read_run_history_response.download_run_history.downloaded_files
        ]
        errors = {
            pathlib.Path(file_name): error_message
            for file_name, error_message in response.read_run_history_response.download_run_history.errors.items()
        }

        self.download_result = DownloadHistoryResult(
            paths=downloaded_files,
            contains_live_data=self.contains_live_data,
            errors=errors,
        )

        self.done_event.set()

    async def _show_progress_until_done(self) -> None:
        p = new_printer()
        with progress_printer(p, "Downloading history...") as progress:
            while not await self._rate_limit_check_done():
                status_request = apb.ApiRequest(
                    read_run_history_request=apb.ReadRunHistoryRequest(
                        download_run_history_status=apb.DownloadRunHistoryStatus(
                            request_id=self.request_id,
                        )
                    )
                )
                handle = await self.api._send_api_request_async(status_request)
                last_response = await handle.wait_async(timeout=None)

                if last_response is not None:
                    progress.update(
                        last_response.read_run_history_response.download_run_history_status.operation_stats,
                    )

    async def _rate_limit_check_done(self) -> bool:
        """Wait for rate limit and return whether _done is set."""
        now = time.monotonic()
        last_time = self._rate_limit_last_time
        self._rate_limit_last_time = now

        if last_time and (time_since_last := now - last_time) < _POLL_WAIT_SECONDS:
            await asyncio_compat.race(
                asyncio.sleep(_POLL_WAIT_SECONDS - time_since_last),
                self.done_event.wait(),
            )

        return self.done_event.is_set()
