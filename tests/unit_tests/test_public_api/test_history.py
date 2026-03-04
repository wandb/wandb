from unittest.mock import MagicMock

from wandb.apis.public.history import BetaHistoryScan


def test_beta_scan_history_terminates_when_history_exhausted_before_max_step():
    service_api = MagicMock()
    service_api.send_api_request.return_value.read_run_history_response.scan_run_history_init.request_id = 42

    run = MagicMock()
    run.entity = "entity"
    run.project = "project"
    run.id = "run_id"

    scan = BetaHistoryScan(
        service_api=service_api,
        run=run,
        min_step=0,
        max_step=100,  # Much larger than actual history
        page_size=2,
    )

    # Patch _load_next on the instance:
    # - call 1: returns 2 rows (the run's actual history)
    # - call 2: returns empty (history exhausted before max_step)
    # - call 3+: assert catches any infinite loop
    call_count = 0
    pages = [[{"_step": 0, "acc": 0.5}, {"_step": 1, "acc": 0.75}], []]

    def mock_load_next():
        nonlocal call_count
        assert call_count < len(pages), f"_load_next called too many times — infinite loop"
        scan.rows = pages[call_count]
        scan.page_offset += scan.page_size
        scan.scan_offset = 0
        call_count += 1

    scan._load_next = mock_load_next

    assert list(scan) == [{"_step": 0, "acc": 0.5}, {"_step": 1, "acc": 0.75}]
