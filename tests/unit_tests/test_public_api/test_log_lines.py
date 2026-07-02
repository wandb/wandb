from unittest import mock

import pytest
from wandb.apis.public.log_lines import LogLine, LogLines
from wandb.apis.public.runs import Run


def _run(service_api):
    return Run(
        service_api=service_api,
        entity="entity",
        project="project",
        run_id="run-id",
        attrs={"name": "run-id", "state": "finished"},
    )


def _node(number, line, **overrides):
    node = {
        "number": number,
        "timestamp": "2026-01-01T00:00:00Z",
        "level": "info",
        "label": "",
        "line": line,
    }
    node.update(overrides)
    return {"node": node, "cursor": f"c{number}"}


def _page(log_line_count, edges, has_next, end_cursor="c"):
    return {
        "project": {
            "run": {
                "logLineCount": log_line_count,
                "logLines": {
                    "edges": edges,
                    "pageInfo": {"endCursor": end_cursor, "hasNextPage": has_next},
                },
            }
        }
    }


def test_run_log_lines_returns_paginator():
    service_api = mock.MagicMock()
    run = _run(service_api)
    assert isinstance(run.log_lines(), LogLines)


def test_tail_is_a_single_request():
    service_api = mock.MagicMock()
    run = _run(service_api)
    service_api.execute_graphql.return_value = _page(
        1512, [_node(1510, "second to last"), _node(1511, "last")], has_next=False
    )

    lines = list(run.log_lines(last=2))

    assert [line.line for line in lines] == ["second to last", "last"]
    assert isinstance(lines[0], LogLine)
    # tail = exactly one request, carrying `last`, not forward-pagination args
    assert service_api.execute_graphql.call_count == 1
    variables = service_api.execute_graphql.call_args.kwargs["variables"]
    assert variables["last"] == 2
    assert variables["first"] is None
    assert variables["after"] is None


def test_log_line_exposes_all_fields():
    service_api = mock.MagicMock()
    run = _run(service_api)
    service_api.execute_graphql.return_value = _page(
        1,
        [_node(7, "boom", level="error", label="rank-1")],
        has_next=False,
    )

    (line,) = list(run.log_lines())

    assert line.number == 7
    assert line.line == "boom"
    assert line.level == "error"
    assert line.label == "rank-1"
    assert line.timestamp == "2026-01-01T00:00:00Z"


def test_len_is_log_line_count():
    service_api = mock.MagicMock()
    run = _run(service_api)
    service_api.execute_graphql.return_value = _page(42, [_node(0, "x")], has_next=False)

    assert len(run.log_lines()) == 42


def test_tail_len_is_tail_size_not_run_total():
    service_api = mock.MagicMock()
    run = _run(service_api)
    service_api.execute_graphql.return_value = _page(
        1512, [_node(1510, "a"), _node(1511, "b")], has_next=False
    )

    tail = run.log_lines(last=2)

    # tail reports the fetched tail (2), not the run's total logLineCount (1512)
    assert len(tail) == 2
    assert [line.number for line in tail] == [1510, 1511]


def test_unsupported_server_raises_before_querying():
    service_api = mock.MagicMock()
    service_api.feature_enabled.return_value = False
    run = _run(service_api)

    with pytest.raises(ValueError, match="structured console logs"):
        run.log_lines()

    service_api.execute_graphql.assert_not_called()


def test_forward_pagination_advances_cursor():
    service_api = mock.MagicMock()
    run = _run(service_api)
    pages = [
        _page(3, [_node(0, "l0"), _node(1, "l1")], has_next=True, end_cursor="cA"),
        _page(3, [_node(2, "l2")], has_next=False, end_cursor="cB"),
    ]
    # The paginator reuses one `variables` dict (like `Files`), so snapshot each
    # call's variables here rather than reading the shared, mutated reference.
    seen = []

    def fake_execute(query, variables=None, **kwargs):
        seen.append(dict(variables))
        return pages[len(seen) - 1]

    service_api.execute_graphql.side_effect = fake_execute

    numbers = [line.number for line in run.log_lines(per_page=2)]

    assert numbers == [0, 1, 2]
    assert len(seen) == 2
    assert seen[0]["first"] == 2
    assert seen[0]["after"] is None
    assert seen[0]["last"] is None
    # second page resumes from the last edge cursor of the first page
    assert seen[1]["after"] == "c1"


def test_empty_log():
    service_api = mock.MagicMock()
    run = _run(service_api)
    service_api.execute_graphql.return_value = _page(0, [], has_next=False)

    assert list(run.log_lines()) == []
    assert len(run.log_lines()) == 0
