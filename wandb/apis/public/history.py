"""W&B Public API for Run History.

This module provides classes for efficiently scanning and sampling run
history data.

Note:
    This module is part of the W&B Public API and provides methods
    to access run history data. It handles pagination automatically and offers
    both complete and sampled access to metrics logged during training runs.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any, TypeAlias

from typing_extensions import Self

from wandb.proto import wandb_api_pb2 as pb

if TYPE_CHECKING:
    from . import runs
    from .service_api import ServiceApi

_RowDict: TypeAlias = dict[str, Any]
"""Type alias for a single history row as a dict."""


class HistoryScan(Iterator[_RowDict]):
    """Iterator for scanning complete run history.

    <!-- lazydoc-ignore-class: internal -->
    """

    def __init__(
        self,
        run: runs.Run,
        *,
        service_api: ServiceApi,
        min_step: int,
        max_step: int,
        keys: list[str] | None = None,
        page_size: int = 1_000,
        use_cache: bool = True,
    ):
        self.run = run
        self.min_step = min_step
        self._stop_step = max_step
        self.keys = keys
        self.page_size = page_size
        self._service_api = service_api

        # Tell wandb-core to initialize resources to scan the run's history.
        scan_run_history_init = pb.ScanRunHistoryInit(
            entity=self.run.entity,
            project=self.run.project,
            run_id=self.run.id,
            keys=self.keys,
            use_cache=use_cache,
        )
        scan_run_history_init_request = pb.ReadRunHistoryRequest(
            scan_run_history_init=scan_run_history_init
        )
        api_request = pb.ApiRequest(
            read_run_history_request=scan_run_history_init_request
        )
        response: pb.ApiResponse = self._service_api.send_api_request(api_request)

        self._scan_request_id = (
            response.read_run_history_response.scan_run_history_init.request_id
        )

        self.scan_offset = 0
        self.page_offset = self.min_step
        self.rows: list[_RowDict] = []
        self.keys = keys

        # Clean up resources when the object is GC'ed.
        self._service_api.finalize(
            self,
            _scan_cleanup_request(self._scan_request_id),
        )

    @property
    def max_step(self) -> int:
        """The highest step that can be yielded by this scan."""
        return self._stop_step - 1

    def __iter__(self) -> Self:
        self.scan_offset = 0
        self.page_offset = self.min_step
        self.rows = []
        return self

    def __next__(self) -> _RowDict:
        while True:
            if self.scan_offset < len(self.rows):
                row = self.rows[self.scan_offset]
                self.scan_offset += 1
                return row
            if self.page_offset >= self._stop_step:
                raise StopIteration()
            # Load the next page. An empty page does not terminate the scan: a
            # step range may have no rows while later steps do (e.g. a gap
            # between exported parquet data and the live tail). Iteration ends
            # only once page_offset reaches _stop_step (checked above).
            self._load_next()

    def _load_next(self) -> None:
        from wandb.proto import wandb_api_pb2 as pb

        max_step = min(self.page_offset + self.page_size, self._stop_step)

        read_run_history_request = pb.ReadRunHistoryRequest(
            scan_run_history=pb.ScanRunHistory(
                min_step=self.page_offset,
                max_step=max_step,
                request_id=self._scan_request_id,
            ),
        )
        api_request = pb.ApiRequest(read_run_history_request=read_run_history_request)

        response: pb.ApiResponse = self._service_api.send_api_request(api_request)
        run_history: pb.RunHistoryResponse = (
            response.read_run_history_response.run_history
        )
        self.rows = [
            self._convert_history_row_to_dict(row) for row in run_history.history_rows
        ]
        self.page_offset += self.page_size
        self.scan_offset = 0

    @staticmethod
    def _convert_history_row_to_dict(history_row: pb.HistoryRow) -> _RowDict:
        return {
            item.key: json.loads(item.value_json) for item in history_row.history_items
        }


def _scan_cleanup_request(id: int) -> pb.ApiRequest:
    """Returns a ScanRunHistoryCleanup request for the given ID."""
    scan_cleanup_request = pb.ScanRunHistoryCleanup(request_id=id)
    run_history_request = pb.ReadRunHistoryRequest(
        scan_run_history_cleanup=scan_cleanup_request,
    )

    return pb.ApiRequest(read_run_history_request=run_history_request)
