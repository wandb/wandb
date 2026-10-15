import json
from collections.abc import Callable
from types import SimpleNamespace

import pytest
from wandb.apis.public.history import HistoryScan
from wandb.proto import wandb_api_pb2 as apb


class FakeServiceApi:
    def __init__(self, pages, next_steps=None):
        self.pages = list(pages)
        self.scan_ranges = []
        self.next_steps = iter(next_steps) if next_steps is not None else None

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
            page = apb.RunHistoryResponse(history_rows=self.pages.pop(0))
            if self.next_steps is not None:
                page.next_step = next(self.next_steps)
            return apb.ApiResponse(
                read_run_history_response=apb.ReadRunHistoryResponse(run_history=page)
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


def test_scan_history_jumps_between_sparse_exported_rows():
    steps = [
        0,
        983040,
        1966080,
        2949120,
        3932160,
        4915200,
        5898240,
        6881280,
        7864320,
        100208640,
    ]
    service_api = FakeServiceApi(
        pages=[
            [history_row(_step=step, loss=index)] for index, step in enumerate(steps)
        ],
        next_steps=[*steps[1:], 2**63 - 1],
    )
    scan = HistoryScan(
        service_api=service_api,
        run=SimpleNamespace(entity="entity", project="project", id="run-id"),
        min_step=0,
        max_step=steps[-1] + 1,
    )

    assert list(scan) == [
        {"_step": step, "loss": index} for index, step in enumerate(steps)
    ]
    assert service_api.scan_ranges == [
        (step, min(step + 1000, steps[-1] + 1)) for step in steps
    ]


@pytest.mark.parametrize("hint", [0, 1, 2])
def test_scan_history_hint_cannot_repeat_a_window(hint):
    service_api = FakeServiceApi(
        pages=[[history_row(_step=0)], [history_row(_step=2)]],
        next_steps=[hint, 2**63 - 1],
    )
    scan = HistoryScan(
        service_api=service_api,
        run=SimpleNamespace(entity="entity", project="project", id="run-id"),
        min_step=0,
        max_step=4,
        page_size=2,
    )
    assert list(scan) == [{"_step": 0}, {"_step": 2}]
    assert service_api.scan_ranges == [(0, 2), (2, 4)]


def test_scan_history_jump_from_empty_page_preserves_exclusive_bound():
    service_api = FakeServiceApi(
        pages=[[], [history_row(_step=10)], [history_row(_step=12)]],
        next_steps=[10, 12, 14],
    )
    scan = HistoryScan(
        service_api=service_api,
        run=SimpleNamespace(entity="entity", project="project", id="run-id"),
        min_step=2,
        max_step=13,
        page_size=2,
    )
    assert list(scan) == [{"_step": 10}, {"_step": 12}]
    assert service_api.scan_ranges == [(2, 4), (10, 12), (12, 13)]
