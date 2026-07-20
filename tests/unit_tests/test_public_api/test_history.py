import json
from collections.abc import Callable
from types import SimpleNamespace

from wandb.apis.public.history import HistoryScan
from wandb.proto import wandb_api_pb2 as apb


class FakeServiceApi:
    def __init__(self, pages):
        self.pages = list(pages)
        self.scan_ranges = []

    def send_api_request(self, request):
        read_request = request.read_run_history_request

        if read_request.HasField("scan_run_history_init"):
            return apb.ApiResponse(
                read_run_history_response=apb.ReadRunHistoryResponse(
                    scan_run_history_init=apb.ScanRunHistoryInitResponse(request_id=1)
                )
            )

        if read_request.HasField("scan_run_history"):
            scan_request = read_request.scan_run_history
            self.scan_ranges.append((scan_request.min_step, scan_request.max_step))
            return apb.ApiResponse(
                read_run_history_response=apb.ReadRunHistoryResponse(
                    run_history=apb.RunHistoryResponse(history_rows=self.pages.pop(0))
                )
            )

        return apb.ApiResponse(
            read_run_history_response=apb.ReadRunHistoryResponse(
                scan_run_history_cleanup=apb.ScanRunHistoryCleanupResponse()
            )
        )

    def finalize(self, *args, **kwargs) -> Callable[[], None]:
        return lambda: None


def history_row(**items):
    return apb.HistoryRow(
        history_items=[
            apb.ParquetHistoryItem(key=key, value_json=json.dumps(value))
            for key, value in items.items()
        ]
    )


def test_scan_history_skips_empty_pages_before_later_history():
    service_api = FakeServiceApi(
        pages=[
            [],
            [
                history_row(_step=2, acc=0.5),
                history_row(_step=3, acc=0.75),
            ],
        ]
    )
    run = SimpleNamespace(entity="entity", project="project", id="run-id")

    scan = HistoryScan(
        service_api=service_api,
        run=run,
        min_step=0,
        max_step=4,
        page_size=2,
    )

    assert list(scan) == [
        {"_step": 2, "acc": 0.5},
        {"_step": 3, "acc": 0.75},
    ]
    assert service_api.scan_ranges == [(0, 2), (2, 4)]
