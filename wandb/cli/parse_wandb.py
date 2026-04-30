from __future__ import annotations

import contextlib
import os
import pathlib
import sys
import weakref
from collections.abc import Iterator
from typing import Any

from typing_extensions import Self

from wandb.apis.public.service_api import ServiceApi
from wandb.proto import wandb_api_pb2 as pb
from wandb.sdk import wandb_setup
from wandb.sdk.mailbox.mailbox import MailboxClosedError


class ParseRunFileScan(Iterator[dict[str, Any]]):
    """Iterator that reads records from a .wandb file via wandb-core."""

    def __init__(
        self,
        service_api: ServiceApi,
        path: pathlib.Path,
        record_types: list[str] | None = None,
        page_size: int = 100,
    ) -> None:
        """Initialize the scan.

        Args:
            service_api: The service API to use.
            path: The path to the .wandb file.
            record_types: The record types to filter by.
            page_size: The page size to use.
        """
        if not path.is_file():
            raise ValueError(f".wandb file not found: {path}")
        if path.stat().st_size == 0:
            raise ValueError(f".wandb file is empty or invalid: {path}")

        self._service_api = service_api
        self._record_types = record_types or []
        self._page_size = page_size
        self._eof = False
        self._scan_offset = 0
        self._records: list[dict[str, Any]] = []

        init_request = pb.ApiRequest(
            parse_run_file_request=pb.ParseRunFileRequest(
                parse_run_file_init=pb.ParseRunFileInit(path=path),
            ),
        )
        init_response = self._service_api.send_api_request(init_request)
        self._request_id = (
            init_response.parse_run_file_response.parse_run_file_init.request_id
        )

        weakref.finalize(
            self,
            self.cleanup,
            self._service_api,
            self._request_id,
        )

    def __iter__(self) -> Self:
        return self

    def __next__(self) -> dict[str, Any]:
        while True:
            if self._scan_offset < len(self._records):
                record = self._records[self._scan_offset]
                self._scan_offset += 1
                return record
            if self._eof:
                raise StopIteration
            self._load_next()

    def _load_next(self) -> None:
        read_request = pb.ApiRequest(
            parse_run_file_request=pb.ParseRunFileRequest(
                parse_run_file_read=pb.ParseRunFileRead(
                    request_id=self._request_id,
                    page_size=self._page_size,
                    record_types=self._record_types,
                ),
            ),
        )
        read_response = self._service_api.send_api_request(read_request)
        page = read_response.parse_run_file_response.parse_run_file_read

        self._records = [
            {
                "record_type": r.record_type,
                "record_num": r.record_num,
                "json_content": r.json_content,
            }
            for r in page.records
        ]
        self._scan_offset = 0
        self._eof = page.eof

    @staticmethod
    def cleanup(service_api: ServiceApi, request_id: int) -> None:
        cleanup_request = pb.ApiRequest(
            parse_run_file_request=pb.ParseRunFileRequest(
                parse_run_file_cleanup=pb.ParseRunFileCleanup(
                    request_id=request_id,
                ),
            ),
        )
        with contextlib.suppress(ConnectionResetError, MailboxClosedError):
            service_api._get_service_connection().api_publish(cleanup_request)


def parse(
    path: pathlib.Path,
    *,
    output: str | None,
    record_types: list[str] | None,
    page_size: int,
) -> None:
    """Read a .wandb file via wandb-core and print records as JSON lines."""
    singleton = wandb_setup.singleton()
    settings = singleton.settings.model_copy()
    service_api = ServiceApi(settings=settings)

    scanner = ParseRunFileScan(
        service_api=service_api,
        path=path.absolute(),
        record_types=record_types,
        page_size=page_size,
    )

    out = open(output, "w") if output else sys.stdout
    try:
        for record in scanner:
            out.write(record["json_content"] + "\n")
    finally:
        if output:
            out.close()
