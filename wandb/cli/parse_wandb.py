"""Implements ``wandb parse`` using wandb-core's Go transactionlog reader."""

from __future__ import annotations

import os
import sys

from wandb.apis.public.service_api import ServiceApi
from wandb.proto import wandb_api_pb2 as pb
from wandb.sdk import wandb_setup


def parse(
    path: str,
    *,
    output: str | None,
    record_types: list[str] | None,
    page_size: int,
) -> None:
    """Read a .wandb file via wandb-core and print records as JSON lines."""
    abs_path = os.path.abspath(path)

    singleton = wandb_setup.singleton()
    settings = singleton.settings.model_copy()
    service_api = ServiceApi(settings=settings)

    init_request = pb.ApiRequest(
        parse_run_file_request=pb.ParseRunFileRequest(
            parse_run_file_init=pb.ParseRunFileInit(path=abs_path),
        ),
    )
    init_response = service_api.send_api_request(init_request)
    request_id = init_response.parse_run_file_response.parse_run_file_init.request_id

    out = open(output, "w") if output else sys.stdout  # noqa: SIM115

    try:
        while True:
            read_request = pb.ApiRequest(
                parse_run_file_request=pb.ParseRunFileRequest(
                    parse_run_file_read=pb.ParseRunFileRead(
                        request_id=request_id,
                        page_size=page_size,
                        record_types=record_types or [],
                    ),
                ),
            )
            read_response = service_api.send_api_request(read_request)
            page = read_response.parse_run_file_response.parse_run_file_read

            for record in page.records:
                out.write(record.json_content + "\n")

            if page.eof:
                break
    finally:
        cleanup_request = pb.ApiRequest(
            parse_run_file_request=pb.ParseRunFileRequest(
                parse_run_file_cleanup=pb.ParseRunFileCleanup(
                    request_id=request_id,
                ),
            ),
        )
        service_api._get_service_connection().api_publish(cleanup_request)

        if output:
            out.close()
