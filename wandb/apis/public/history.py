"""W&B Public API for Run History.

This module provides classes for efficiently scanning and sampling run
history data.

Note:
    This module is part of the W&B Public API and provides methods
    to access run history data. It handles pagination automatically and offers
    both complete and sampled access to metrics logged during training runs.
"""

from __future__ import annotations

import contextlib
import json
import weakref
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from typing_extensions import Self, TypeAlias
from wandb_gql import gql

from wandb.apis.normalize import normalize_exceptions
from wandb.apis.public.service_api import ServiceAPI
from wandb.proto import wandb_api_pb2 as pb
from wandb.sdk.mailbox.mailbox import MailboxClosedError

if TYPE_CHECKING:
    from . import runs
    from .api import RetryingClient

_RowDict: TypeAlias = dict[str, Any]
"""Type alias for a single history row as a dict."""


class BetaHistoryScan(Iterator[_RowDict]):
    """Iterator for scanning complete run history.

    <!-- lazydoc-ignore-class: internal -->
    """

    def __init__(
        self,
        service_api: ServiceAPI,
        run: runs.Run,
        min_step: int,
        max_step: int,
        keys: list[str] | None = None,
        page_size: int = 1_000,
        use_cache: bool = True,
    ):
        self.run = run
        self.min_step = min_step
        self.max_step = max_step
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
        self.rows: list[_RowDict] = []
        self.keys = keys

        # Add cleanup hook to clean up resources in wandb-core
        # when this scan object is deleted.
        #
        # Using weakref.finalize ensures that references to objects needed during cleanup
        # are not garbage collected before being used.
        # see: https://docs.python.org/3/library/weakref.html#comparing-finalizers-with-del-methods
        weakref.finalize(
            self,
            self.cleanup,
            self._service_api,
            self._scan_request_id,
        )

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
            if self.page_offset >= self.max_step:
                raise StopIteration()
            self._load_next()

    def _load_next(self) -> None:
        from wandb.proto import wandb_api_pb2 as pb

        max_step = min(self.page_offset + self.page_size, self.max_step)

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

    @staticmethod
    def cleanup(service_api: ServiceAPI, request_id: int) -> None:
        scan_run_history_cleanup = pb.ScanRunHistoryCleanup(
            request_id=request_id,
        )
        scan_run_history_cleanup_request = pb.ReadRunHistoryRequest(
            scan_run_history_cleanup=scan_run_history_cleanup
        )

        with contextlib.suppress(ConnectionResetError, MailboxClosedError):
            service_api.send_api_request(
                pb.ApiRequest(read_run_history_request=scan_run_history_cleanup_request)
            )


class HistoryScan(Iterator[_RowDict]):
    """Iterator for scanning complete run history.

    <!-- lazydoc-ignore-class: internal -->
    """

    QUERY = gql(
        """
        query HistoryPage($entity: String!, $project: String!, $run: String!, $minStep: Int64!, $maxStep: Int64!, $pageSize: Int!) {
            project(name: $project, entityName: $entity) {
                run(name: $run) {
                    history(minStep: $minStep, maxStep: $maxStep, samples: $pageSize)
                }
            }
        }
        """
    )

    def __init__(
        self,
        client: RetryingClient,
        run: runs.Run,
        min_step: int,
        max_step: int,
        page_size: int = 1_000,
    ):
        """Initialize a HistoryScan instance.

        Args:
            client: The client instance to use for making API calls to the W&B backend.
            run: The run object whose history is to be scanned.
            min_step: The minimum step to start scanning from.
            max_step: The maximum step to scan up to.
            page_size: Number of history rows to fetch per page.
                Default page_size is 1000.
        """
        self.client = client
        self.run = run
        self.page_size = page_size
        self.min_step = min_step
        self.max_step = max_step
        self.page_offset = min_step  # minStep for next page
        self.scan_offset = 0  # index within current page of rows
        self.rows: list[_RowDict] = []  # current page of rows

    def __iter__(self) -> Self:
        self.page_offset = self.min_step
        self.scan_offset = 0
        self.rows = []
        return self

    def __next__(self) -> _RowDict:
        """Return the next row of history data with automatic pagination.

        <!-- lazydoc-ignore: internal -->
        """
        while True:
            if self.scan_offset < len(self.rows):
                row = self.rows[self.scan_offset]
                self.scan_offset += 1
                return row
            if self.page_offset >= self.max_step:
                raise StopIteration()
            self._load_next()

    next = __next__

    @normalize_exceptions
    def _load_next(self) -> None:
        max_step = self.page_offset + self.page_size
        if max_step > self.max_step:
            max_step = self.max_step
        variables = {
            "entity": self.run.entity,
            "project": self.run.project,
            "run": self.run.id,
            "minStep": int(self.page_offset),
            "maxStep": int(max_step),
            "pageSize": int(self.page_size),
        }

        res = self.client.execute(self.QUERY, variable_values=variables)
        res = res["project"]["run"]["history"]
        self.rows = [json.loads(row) for row in res]
        self.page_offset += self.page_size
        self.scan_offset = 0


class SampledHistoryScan(Iterator[_RowDict]):
    """Iterator for sampling run history data.

    <!-- lazydoc-ignore-class: internal -->
    """

    QUERY = gql(
        """
        query SampledHistoryPage($entity: String!, $project: String!, $run: String!, $spec: JSONString!) {
            project(name: $project, entityName: $entity) {
                run(name: $run) {
                    sampledHistory(specs: [$spec])
                }
            }
        }
        """
    )

    def __init__(
        self,
        client: RetryingClient,
        run: runs.Run,
        keys: list[str],
        min_step: int,
        max_step: int,
        page_size: int = 1_000,
    ):
        """Initialize a SampledHistoryScan instance.

        Args:
            client: The client instance to use for making API calls to the W&B backend.
            run: The run object whose history is to be sampled.
            keys: List of keys to sample from the history.
            min_step: The minimum step to start sampling from.
            max_step: The maximum step to sample up to.
            page_size: Number of sampled history rows to fetch per page.
                Default page_size is 1000.
        """
        self.client = client
        self.run = run
        self.keys = keys
        self.page_size = page_size
        self.min_step = min_step
        self.max_step = max_step
        self.page_offset = min_step  # minStep for next page
        self.scan_offset = 0  # index within current page of rows
        self.rows: list[_RowDict] = []  # current page of rows

    def __iter__(self) -> Self:
        self.page_offset = self.min_step
        self.scan_offset = 0
        self.rows = []
        return self

    def __next__(self) -> _RowDict:
        """Return the next row of sampled history data with automatic pagination.

        <!-- lazydoc-ignore: internal -->
        """
        while True:
            if self.scan_offset < len(self.rows):
                row = self.rows[self.scan_offset]
                self.scan_offset += 1
                return row
            if self.page_offset >= self.max_step:
                raise StopIteration()
            self._load_next()

    next = __next__

    @normalize_exceptions
    def _load_next(self) -> None:
        max_step = self.page_offset + self.page_size
        if max_step > self.max_step:
            max_step = self.max_step
        variables = {
            "entity": self.run.entity,
            "project": self.run.project,
            "run": self.run.id,
            "spec": json.dumps(
                {
                    "keys": self.keys,
                    "minStep": int(self.page_offset),
                    "maxStep": int(max_step),
                    "samples": int(self.page_size),
                }
            ),
        }

        res = self.client.execute(self.QUERY, variable_values=variables)
        res = res["project"]["run"]["sampledHistory"]
        self.rows = res[0]
        self.page_offset += self.page_size
        self.scan_offset = 0
