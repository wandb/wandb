from datetime import datetime, timezone
from unittest import mock

import pytest
from wandb.apis.public.console_logs import _parse_timestamp
from wandb.apis.public.runs import Run
from wandb.proto import wandb_api_pb2 as apb


def _run(service_api):
    return Run(
        service_api=service_api,
        entity="entity",
        project="project",
        run_id="run-id",
        attrs={"name": "run-id", "state": "finished"},
    )


def _line(number, content, **overrides):
    fields = {
        "number": number,
        "timestamp": "2026-01-01T00:00:00Z",
        "level": "info",
        "label": "",
        "content": content,
    }
    fields.update(overrides)
    return apb.RunConsoleLogLine(**fields)


def _response(lines, end_cursor="", has_next_page=False, total_lines=0):
    return apb.ApiResponse(
        read_run_console_logs_response=apb.ReadRunConsoleLogsResponse(
            lines=lines,
            end_cursor=end_cursor,
            has_next_page=has_next_page,
            total_lines=total_lines,
        )
    )


def test_line_exposes_all_fields():
    service_api = mock.MagicMock()
    run = _run(service_api)
    service_api.send_api_request.return_value = _response(
        [_line(7, "boom", level="error", label="rank-1")],
        end_cursor="c7",
        total_lines=1,
    )

    (line,) = list(run.console_logs())

    assert line.number == 7
    assert line.content == "boom"
    assert line.level == "error"
    assert line.label == "rank-1"
    assert line.timestamp == datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_forward_pagination_advances_cursor():
    service_api = mock.MagicMock()
    run = _run(service_api)
    service_api.send_api_request.side_effect = [
        _response(
            [_line(0, "l0"), _line(1, "l1")],
            end_cursor="c1",
            has_next_page=True,
            total_lines=3,
        ),
        _response([_line(2, "l2")], end_cursor="c2", total_lines=3),
    ]

    numbers = [line.number for line in run.console_logs(per_page=2)]

    assert numbers == [0, 1, 2]
    assert service_api.send_api_request.call_count == 2

    first_request = service_api.send_api_request.call_args_list[0].args[0]
    assert first_request.read_run_console_logs_request.first == 2
    assert not first_request.read_run_console_logs_request.HasField("after")
    assert not first_request.read_run_console_logs_request.HasField("last")

    # The second page resumes after the cursor of the first page.
    second_request = service_api.send_api_request.call_args_list[1].args[0]
    assert second_request.read_run_console_logs_request.first == 2
    assert second_request.read_run_console_logs_request.after == "c1"


def test_empty_log():
    service_api = mock.MagicMock()
    run = _run(service_api)
    service_api.send_api_request.return_value = _response([])

    assert list(run.console_logs()) == []


def test_tail_larger_than_log_yields_only_fetched_lines():
    service_api = mock.MagicMock()
    run = _run(service_api)
    service_api.send_api_request.return_value = _response(
        [_line(0, "a"), _line(1, "b"), _line(2, "c")], total_lines=3
    )

    tail = run.console_logs(last=10)

    # The log has fewer lines than requested, so iteration yields only
    # the available lines.
    assert [line.number for line in tail] == [0, 1, 2]
    service_api.send_api_request.assert_called_once()


def test_short_page_with_next_page_continues():
    # A non-final page may hold fewer lines than per_page; termination
    # must follow has_next_page, not the fetched line count.
    service_api = mock.MagicMock()
    run = _run(service_api)
    service_api.send_api_request.side_effect = [
        _response([_line(0, "l0")], end_cursor="c0", has_next_page=True, total_lines=3),
        _response([_line(1, "l1"), _line(2, "l2")], end_cursor="c2", total_lines=3),
    ]

    numbers = [line.number for line in run.console_logs(per_page=2)]

    assert numbers == [0, 1, 2]
    assert service_api.send_api_request.call_count == 2


def test_next_page_without_cursor_stops_instead_of_restarting():
    # A next page without a cursor to resume from cannot be fetched;
    # requesting without `after` would re-read the log from the start and
    # yield duplicate lines forever.
    service_api = mock.MagicMock()
    run = _run(service_api)
    service_api.send_api_request.return_value = _response(
        [_line(0, "l0"), _line(1, "l1")],
        end_cursor="",
        has_next_page=True,
        total_lines=4,
    )

    numbers = [line.number for line in run.console_logs()]

    assert numbers == [0, 1]
    service_api.send_api_request.assert_called_once()


def test_request_failure_surfaces_when_iterating():
    from wandb.errors import CommError
    from wandb.sdk.lib.service.service_connection import WandbApiFailedError

    service_api = mock.MagicMock()
    run = _run(service_api)
    service_api.send_api_request.side_effect = WandbApiFailedError(
        "run e/p/r not found"
    )

    logs = run.console_logs()

    with pytest.raises(CommError, match="not found"):
        list(logs)


@pytest.mark.parametrize(
    "value,expected",
    [
        (
            "2026-01-02T03:04:05Z",
            datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
        ),
        (
            "2026-01-02T03:04:05.678Z",
            datetime(2026, 1, 2, 3, 4, 5, 678000, tzinfo=timezone.utc),
        ),
        # Nanosecond precision, more than fromisoformat accepts before 3.11.
        (
            "2026-01-02T03:04:05.678901234Z",
            datetime(2026, 1, 2, 3, 4, 5, 678901, tzinfo=timezone.utc),
        ),
        # Short fraction: fromisoformat accepts only 3- or 6-digit
        # fractions before Python 3.11.
        (
            "2026-01-02T03:04:05.12Z",
            datetime(2026, 1, 2, 3, 4, 5, 120000, tzinfo=timezone.utc),
        ),
        (
            "2026-01-02T03:04:05+02:00",
            datetime(2026, 1, 2, 1, 4, 5, tzinfo=timezone.utc),
        ),
        # The backend records UTC timestamps without a zone designator.
        (
            "2026-01-02T03:04:05.678901",
            datetime(2026, 1, 2, 3, 4, 5, 678901, tzinfo=timezone.utc),
        ),
        ("", None),
        ("not a timestamp", None),
    ],
)
def test_parse_timestamp(value, expected):
    assert _parse_timestamp(value) == expected
