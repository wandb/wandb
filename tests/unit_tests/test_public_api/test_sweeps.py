from __future__ import annotations

import gc
import re
from typing import Any

import pytest
import requests
import wandb
from wandb.apis._generated import GET_SWEEP_GQL, GET_SWEEPS_GQL
from wandb.apis.public.sweeps import Sweep, _SweepLogStream

_TIMESTAMP_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)? ")


def _make_sweep(attrs: dict[str, Any]) -> Sweep:
    """Construct a Sweep with attrs so that no network load() occurs."""
    return Sweep(object(), "e", "p", "s", attrs=attrs)


class _FakeInternalApi:
    def __init__(self, *args, **kwargs):
        pass

    @property
    def request_auth(self) -> tuple[str, str]:
        return ("api", "fake-api-key")

    @property
    def request_headers(self) -> dict[str, str]:
        return {"User-Agent": "test-agent"}

    @property
    def request_proxies(self) -> dict[str, str]:
        return {}

    def settings(self, key: str | None = None) -> Any:
        assert key == "base_url"
        return "https://api.test.example"


@pytest.fixture
def posted_calls(monkeypatch) -> list[dict[str, Any]]:
    """Stub out InternalApi and request_with_retry, capturing POSTs."""
    calls: list[dict[str, Any]] = []

    def fake_request_with_retry(func, url, **kwargs):
        # func is the bound session.post; capture headers at call time.
        calls.append(
            {
                "url": url,
                "json": kwargs.get("json"),
                "kwargs": kwargs,
                "headers": dict(func.__self__.headers),
            }
        )
        return requests.Response()

    monkeypatch.setattr(
        "wandb.sdk.internal.internal_api.Api",
        _FakeInternalApi,
    )
    monkeypatch.setattr(
        "wandb.sdk.internal.file_stream.request_with_retry",
        fake_request_with_retry,
    )
    return calls


def test_controller_run_name_in_get_sweep_query_only():
    assert "controllerRunName" in GET_SWEEP_GQL
    assert "controllerRunName" not in GET_SWEEPS_GQL


def test_controller_run_name_property():
    sweep = _make_sweep({"name": "s", "controllerRunName": "abc123"})
    assert sweep.controller_run_name == "abc123"


@pytest.mark.parametrize(
    "attrs",
    [
        {"name": "s"},
        {"name": "s", "controllerRunName": ""},
    ],
)
def test_controller_run_name_property_missing_or_empty(attrs):
    sweep = _make_sweep(attrs)
    assert sweep.controller_run_name is None


def _flush(sweep) -> None:
    """Force the background sender to deliver everything queued so far."""
    if sweep._log_stream is not None:
        sweep._log_stream.finish()


def _all_content(posted_calls) -> list[str]:
    """Flatten output.log content across every captured POST."""
    return [
        line
        for call in posted_calls
        for line in call["json"]["files"]["output.log"]["content"]
    ]


def test_log_happy_path(posted_calls):
    sweep = _make_sweep({"name": "s", "controllerRunName": "abc123"})

    sweep.log("hello world")
    _flush(sweep)

    assert len(posted_calls) == 1
    call = posted_calls[0]
    assert call["url"] == "https://api.test.example/files/e/p/abc123/file_stream"

    body = call["json"]
    assert set(body.keys()) == {"files", "dropped"}
    assert body["dropped"] == 0
    assert set(body["files"].keys()) == {"output.log"}
    assert body["files"]["output.log"]["offset"] == 0

    content = body["files"]["output.log"]["content"]
    assert len(content) == 1
    assert content[0].endswith("\n")
    assert _TIMESTAMP_PREFIX_RE.match(content[0])
    assert content[0].rstrip("\n").endswith(" hello world")


def test_log_stream_reused_across_calls(posted_calls):
    sweep = _make_sweep({"name": "s", "controllerRunName": "abc123"})

    sweep.log("one", add_timestamps=False)
    stream_after_first = sweep._log_stream
    sweep.log("two", add_timestamps=False)
    _flush(sweep)

    # The background sender is built lazily once and reused across calls.
    assert stream_after_first is not None
    assert sweep._log_stream is stream_after_first
    # Both lines are delivered (batched into one or more posts).
    assert _all_content(posted_calls) == ["one\n", "two\n"]


def test_log_list_input_without_timestamps(posted_calls):
    sweep = _make_sweep({"name": "s", "controllerRunName": "abc123"})

    sweep.log(["line one", "line two"], add_timestamps=False)
    _flush(sweep)

    assert _all_content(posted_calls) == ["line one\n", "line two\n"]


def test_log_splits_embedded_newlines(posted_calls):
    sweep = _make_sweep({"name": "s", "controllerRunName": "abc123"})

    sweep.log("a\nb", add_timestamps=False)
    _flush(sweep)

    assert _all_content(posted_calls) == ["a\n", "b\n"]


def test_log_drops_trailing_newline_segment(posted_calls):
    sweep = _make_sweep({"name": "s", "controllerRunName": "abc123"})

    sweep.log("a\nb\n", add_timestamps=False)
    _flush(sweep)

    assert _all_content(posted_calls) == ["a\n", "b\n"]


def test_log_timestamps_prefix_every_line(posted_calls):
    sweep = _make_sweep({"name": "s", "controllerRunName": "abc123"})

    sweep.log(["x", "y"], add_timestamps=True)
    _flush(sweep)

    content = _all_content(posted_calls)
    assert len(content) == 2
    for line in content:
        assert _TIMESTAMP_PREFIX_RE.match(line)
        assert line.endswith("\n")


@pytest.mark.parametrize("lines", ["", [], [""]])
def test_log_empty_input_is_a_noop(posted_calls, lines):
    sweep = _make_sweep({"name": "s", "controllerRunName": "abc123"})

    sweep.log(lines)
    _flush(sweep)

    assert posted_calls == []
    # Empty input never even builds the background sender.
    assert sweep._log_stream is None


def test_log_dict_input_raises_not_implemented(posted_calls):
    sweep = _make_sweep({"name": "s", "controllerRunName": "abc123"})

    with pytest.raises(NotImplementedError, match="history is not"):
        sweep.log({"loss": 0.1, "acc": 0.9})

    assert posted_calls == []


def test_log_without_controller_run_raises_and_makes_no_http_call(posted_calls):
    sweep = _make_sweep({"name": "s"})

    with pytest.raises(wandb.Error, match="no controller run"):
        sweep.log("hello")

    assert posted_calls == []


def test_log_stream_flushed_when_sweep_garbage_collected(posted_calls):
    sweep = _make_sweep({"name": "s", "controllerRunName": "abc123"})
    sweep.log("bye", add_timestamps=False)
    stream = sweep._log_stream
    assert stream is not None
    assert stream._thread.is_alive()

    # Dropping the Sweep must tear down and flush its background sender via the
    # weakref finalizer (the Sweep is not referenced by the stream/thread).
    del sweep
    gc.collect()

    assert stream._finished is True
    assert not stream._thread.is_alive()
    assert _all_content(posted_calls) == ["bye\n"]


def test_log_stream_local_offset_advances_per_batch(posted_calls):
    # Exercise _post directly to avoid depending on background-thread batching
    # timing. The local offset advances by the number of lines each post, even
    # though the backend reassigns real offsets.
    stream = _SweepLogStream(
        requests.Session(),
        "https://api.test.example/files/e/p/abc123/file_stream",
    )

    stream._post(["a\n", "b\n"])
    stream._post(["c\n"])

    offsets = [call["json"]["files"]["output.log"]["offset"] for call in posted_calls]
    assert offsets == [0, 2]
    assert stream._offset == 3


def test_log_stream_thread_crash_is_caught_not_propagated(monkeypatch):
    # An unexpected error in the send loop must be swallowed (logged/Sentry),
    # not propagated out of the daemon thread.
    stream = _SweepLogStream(requests.Session(), "https://api.test.example/fs")

    def boom() -> None:
        raise RuntimeError("kaboom")

    monkeypatch.setattr(stream, "_loop", boom)

    # _run is the thread target; it must return normally despite _loop raising.
    stream._run()


def test_log_stream_post_error_is_dropped_not_raised(monkeypatch):
    # An unexpected error while delivering a batch must not kill the sender;
    # the batch is counted as dropped.
    stream = _SweepLogStream(requests.Session(), "https://api.test.example/fs")

    def boom(_lines: list[str]) -> None:
        raise RuntimeError("kaboom")

    monkeypatch.setattr(stream, "_post_batch", boom)

    stream._post(["a\n", "b\n"])

    assert stream._dropped == 2


def test_log_stream_splits_oversized_batch(posted_calls, monkeypatch):
    from wandb import util

    # Force every line into its own sub-payload to exercise byte-based
    # splitting deterministically without allocating megabytes.
    monkeypatch.setattr(util, "MAX_LINE_BYTES", 1)
    stream = _SweepLogStream(
        requests.Session(),
        "https://api.test.example/files/e/p/abc123/file_stream",
    )

    stream._post(["a\n", "b\n", "c\n"])

    posts = [call["json"]["files"]["output.log"] for call in posted_calls]
    assert [p["offset"] for p in posts] == [0, 1, 2]
    assert [p["content"] for p in posts] == [["a\n"], ["b\n"], ["c\n"]]
    assert stream._offset == 3


def test_log_delivery_failure_is_dropped_not_raised(monkeypatch):
    original_error = requests.exceptions.ConnectionError("boom")

    def failing_request_with_retry(func, url, **kwargs):
        # request_with_retry returns (not raises) the exception on final failure.
        return original_error

    monkeypatch.setattr(
        "wandb.sdk.internal.internal_api.Api",
        _FakeInternalApi,
    )
    monkeypatch.setattr(
        "wandb.sdk.internal.file_stream.request_with_retry",
        failing_request_with_retry,
    )

    sweep = _make_sweep({"name": "s", "controllerRunName": "abc123"})

    # Delivery happens on the background thread, so a failure must not surface
    # to the caller; the line is counted as dropped instead.
    sweep.log("hello")
    _flush(sweep)

    assert sweep._log_stream._dropped == 1
