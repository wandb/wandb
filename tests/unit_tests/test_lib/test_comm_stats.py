from __future__ import annotations

import itertools
import pickle
import sys
import threading
import time
import types

import pytest
from wandb.sdk.lib.comm_stats import CollectiveSummary, CommStatsReporter


def _entry(
    seq,
    *,
    pg=0,
    name="nccl:all_reduce",
    state="completed",
    duration=1.0,
    sizes=((4, 4),),
    dtypes=("Float",),
    p2p=False,
):
    e = {
        "pg_id": pg,
        "collective_seq_id": 0 if p2p else seq,
        "p2p_seq_id": seq if p2p else 0,
        "is_p2p": p2p,
        "profiling_name": name,
        "state": state,
        "input_sizes": [list(s) for s in sizes],
        "input_dtypes": list(dtypes),
    }
    if duration is not None:
        e["duration_ms"] = duration
    return e


class _FakeTorch:
    """Stands in for torch with a scripted NCCL flight recorder."""

    def __init__(self, *, initialized=True, has_dump=True):
        self.entries: list[dict] = []
        self.dump_calls = 0
        self.dump_threads: list[threading.Thread] = []
        self.dump_times: list[float] = []
        self.distributed = types.SimpleNamespace(is_initialized=lambda: initialized)
        c10d = types.SimpleNamespace()
        if has_dump:
            c10d._dump_nccl_trace = self._dump
        self._C = types.SimpleNamespace(_distributed_c10d=c10d)

    def _dump(self, includeCollectives, includeStackTraces, onlyActive):  # noqa: N803
        assert (includeCollectives, includeStackTraces, onlyActive) == (
            True,
            False,
            False,
        )
        self.dump_calls += 1
        self.dump_threads.append(threading.current_thread())
        self.dump_times.append(time.monotonic())
        return pickle.dumps({"version": "2.10", "entries": list(self.entries)})


class _Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def published():
    return []


@pytest.fixture
def lost():
    return []


@pytest.fixture
def torch(monkeypatch):
    t = _FakeTorch()
    monkeypatch.setitem(sys.modules, "torch", t)
    monkeypatch.setenv("TORCH_NCCL_TRACE_BUFFER_SIZE", "2000")
    return t


@pytest.fixture
def reporter(published, lost):
    clock = _Clock()

    def publish(status, colls, n_lost):
        published.append((status, colls))
        lost.append(n_lost)

    r = CommStatsReporter(
        publish,
        interval=60.0,
        clock=clock,
    )
    r.clock = clock
    return r


def test_summary_math(torch, reporter, published):
    torch.entries = [
        _entry(i + 1, duration=float(i + 1), sizes=((1024,),), dtypes=("BFloat16",))
        for i in range(100)
    ] + [
        _entry(
            101,
            name="nccl:all_gather",
            duration=3.0,
            sizes=((8,), (2, 2)),
            dtypes=("Float", "Float"),
        ),
        _entry(102, name="broadcast", duration=5.0, dtypes=("Double",)),
        _entry(103, state="started"),
    ]

    reporter.report()

    assert published == [
        (
            "ok",
            [
                CollectiveSummary("all_gather", 1, 1, 3.0, 3.0, 3.0, 3.0, 48),
                CollectiveSummary(
                    "all_reduce", 100, 100, 50.0, 99.0, 100.0, 5050.0, 204800
                ),
                CollectiveSummary("broadcast", 1, 1, 5.0, 5.0, 5.0, 5.0, 128),
            ],
        )
    ]


def test_unknown_dtype_omits_bytes_for_group(torch, reporter, published):
    torch.entries = [
        _entry(1, dtypes=("Float",)),
        _entry(2, dtypes=("ComplexFloat",)),
        _entry(3, name="nccl:broadcast", dtypes=("Long",)),
    ]

    reporter.report()

    status, colls = published[0]
    assert [(c.name, c.bytes) for c in colls] == [
        ("all_reduce", None),
        ("broadcast", 128),
    ]


def test_dedups_across_dumps_per_process_group(torch, reporter, published):
    torch.entries = [_entry(1, pg=0), _entry(2, pg=0), _entry(1, pg=1)]
    reporter.report()
    torch.entries += [
        _entry(3, pg=0, duration=7.0),
        _entry(2, pg=1, duration=9.0),
        _entry(4, pg=0, state="scheduled"),
    ]
    reporter.clock.t += 60
    reporter.report()

    assert published[0][1][0].count == 3
    assert published[1] == (
        "ok",
        [CollectiveSummary("all_reduce", 2, 2, 7.0, 9.0, 9.0, 16.0, 128)],
    )


def test_ring_wrap_reports_lost_entries(torch, reporter, published, lost):
    torch.entries = [_entry(i) for i in range(1, 2001)]
    reporter.report()
    # 24,000 more complete before the next read; the ring keeps the last 2,000.
    torch.entries = [_entry(i) for i in range(24_001, 26_001)]
    reporter.clock.t += 60
    reporter.report()

    assert [c.count for _, colls in published for c in colls] == [2000, 2000]
    assert lost == [0, 22_000]


def test_ring_wrap_lost_is_per_process_group_and_p2p(torch, reporter, lost):
    torch.entries = [
        _entry(1, pg=0),
        _entry(1, pg=1),
        _entry(1, name="nccl:send", p2p=True),
    ]
    reporter.report()
    torch.entries = [
        _entry(2, pg=0),
        _entry(11, pg=1),
        _entry(6, name="nccl:send", p2p=True),
        _entry(1, pg=7),
    ]
    reporter.clock.t += 60
    reporter.report()

    assert lost == [0, 9 + 4]


def test_no_wrap_when_oldest_entry_is_still_pending(torch, reporter, lost):
    torch.entries = [_entry(1), _entry(2, state="started")]
    reporter.report()
    torch.entries = [_entry(2), _entry(3)]
    reporter.clock.t += 60
    reporter.report()

    assert lost == [0, 0]


def test_lost_counted_once_when_group_reappears(torch, reporter, lost):
    torch.entries = [_entry(1, pg=1)]
    reporter.report()
    torch.entries = [_entry(1, pg=0)]
    reporter.clock.t += 60
    reporter.report()
    torch.entries = [_entry(9, pg=1)]
    reporter.clock.t += 60
    reporter.report()

    assert lost == [0, 0, 7]


def test_p2p_seq_tracked_separately(torch, reporter, published):
    torch.entries = [_entry(5), _entry(1, name="nccl:send", p2p=True)]
    reporter.report()
    torch.entries += [_entry(2, name="nccl:send", p2p=True)]
    reporter.clock.t += 60
    reporter.report()

    assert [(c.name, c.count) for c in published[0][1]] == [
        ("all_reduce", 1),
        ("send", 1),
    ]
    assert [(c.name, c.count) for c in published[1][1]] == [("send", 1)]


def test_no_new_entries_is_ok_and_empty(torch, reporter, published):
    reporter.report()
    assert published == [("ok", [])]


def test_no_timing_sends_counts_only(torch, reporter, published):
    torch.entries = [_entry(1, duration=None), _entry(2, duration=None)]

    reporter.report()

    assert published == [
        (
            "no_timing",
            [CollectiveSummary("all_reduce", 2, 0, None, None, None, None, None)],
        )
    ]


def test_untimed_group_has_no_durations(torch, reporter, published):
    torch.entries = [
        _entry(1, duration=2.0),
        _entry(1, name="nccl:send", p2p=True, duration=None),
    ]

    reporter.report()

    assert published == [
        (
            "ok",
            [
                CollectiveSummary("all_reduce", 1, 1, 2.0, 2.0, 2.0, 2.0, 64),
                CollectiveSummary("send", 1, 0, None, None, None, None, 64),
            ],
        )
    ]


def test_partially_timed_group_counts_timed_entries(torch, reporter, published):
    torch.entries = [_entry(1, duration=2.0), _entry(2, duration=None)]

    reporter.report()

    assert published[0][1] == [
        CollectiveSummary("all_reduce", 2, 1, 2.0, 2.0, 2.0, 2.0, 128)
    ]


def test_falls_back_to_positional_dump_on_type_error(torch, reporter, published):
    def old_dump():
        return pickle.dumps({"entries": [_entry(1)]})

    torch._C._distributed_c10d._dump_nccl_trace = old_dump

    reporter.report()

    assert published[0][0] == "ok"
    assert published[0][1][0].count == 1


def test_no_torch_is_unavailable(monkeypatch, reporter, published):
    monkeypatch.delitem(sys.modules, "torch", raising=False)
    reporter.report()
    assert published == [("unavailable", [])]
    assert "torch" not in sys.modules


@pytest.mark.parametrize(
    "fake, env",
    [
        (_FakeTorch(initialized=False), "2000"),
        (_FakeTorch(has_dump=False), "2000"),
        (_FakeTorch(), None),
        (_FakeTorch(), "0"),
        (_FakeTorch(), "-1"),
    ],
    ids=["not_initialized", "no_dump_function", "env_unset", "env_zero", "env_neg"],
)
def test_unavailable(monkeypatch, reporter, published, fake, env):
    monkeypatch.setitem(sys.modules, "torch", fake)
    monkeypatch.delenv("TORCH_FR_BUFFER_SIZE", raising=False)
    if env is None:
        monkeypatch.delenv("TORCH_NCCL_TRACE_BUFFER_SIZE", raising=False)
    else:
        monkeypatch.setenv("TORCH_NCCL_TRACE_BUFFER_SIZE", env)

    reporter.report()

    assert published == [("unavailable", [])]
    assert fake.dump_calls == 0


def test_fr_buffer_size_env_alias(monkeypatch, torch, reporter, published):
    monkeypatch.delenv("TORCH_NCCL_TRACE_BUFFER_SIZE")
    monkeypatch.setenv("TORCH_FR_BUFFER_SIZE", "100")
    reporter.report()
    assert published == [("ok", [])]


@pytest.mark.parametrize("size, warns", [("5000", 0), ("5001", 1), ("20000", 1)])
def test_large_buffer_warns_once(
    monkeypatch, torch, reporter, published, mock_wandb_log, size, warns
):
    monkeypatch.setenv("TORCH_NCCL_TRACE_BUFFER_SIZE", size)

    reporter.report()
    reporter.clock.t += 120
    reporter.report()

    assert mock_wandb_log._termwarn.call_count == warns
    if warns:
        mock_wandb_log.assert_warned("TORCH_NCCL_TRACE_BUFFER_SIZE")
    assert [status for status, _ in published] == ["ok", "ok"]


def _wait_for(cond, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.005)


def test_not_initialized_publishes_unavailable_rate_limited(
    monkeypatch, reporter, published
):
    fake = _FakeTorch(initialized=False)
    monkeypatch.setitem(sys.modules, "torch", fake)

    reporter.maybe_start()
    reporter.clock.t += 59
    reporter.maybe_start()
    reporter.clock.t += 1
    reporter.maybe_start()

    assert published == [("unavailable", []), ("unavailable", [])]
    assert fake.dump_calls == 0
    assert reporter._thread is None


@pytest.mark.parametrize("interval", [None, 0.0, -5.0])
def test_non_positive_interval_uses_60s(monkeypatch, published, interval):
    monkeypatch.setitem(sys.modules, "torch", _FakeTorch(initialized=False))
    clock = _Clock()
    r = CommStatsReporter(lambda *a: published.append(a), interval, clock=clock)
    r.maybe_start()
    clock.t += 59
    r.maybe_start()
    clock.t += 1
    r.maybe_start()
    assert len(published) == 2


def test_no_torch_maybe_start_never_imports_torch(monkeypatch, reporter, published):
    monkeypatch.delitem(sys.modules, "torch", raising=False)
    reporter.maybe_start()
    assert published == [("unavailable", [])]
    assert "torch" not in sys.modules


def test_reads_on_background_thread_at_interval(torch, published):
    r = CommStatsReporter(lambda *a: published.append(a), 0.05)
    torch.entries = [_entry(1)]
    try:
        r.maybe_start()
        r.maybe_start()
        _wait_for(lambda: torch.dump_calls >= 3)
    finally:
        r.stop()

    assert threading.current_thread() not in torch.dump_threads
    assert len(set(torch.dump_threads)) == 1
    gaps = [b - a for a, b in itertools.pairwise(torch.dump_times)]
    assert min(gaps) >= 0.04
    assert published[0] == (
        "ok",
        [CollectiveSummary("all_reduce", 1, 1, 1.0, 1.0, 1.0, 1.0, 64)],
        0,
    )


def test_stop_ends_thread(torch, published):
    r = CommStatsReporter(lambda *a: published.append(a), 60.0)
    r.maybe_start()
    _wait_for(lambda: torch.dump_calls == 1)

    r.stop()

    assert not r._thread.is_alive()
    r.maybe_start()
    assert torch.dump_calls == 1


def test_stop_without_start_is_noop(reporter):
    reporter.stop()


def test_thread_failure_never_raises_into_caller(torch, published):
    def boom(**kwargs):
        raise RuntimeError("dump failed")

    torch._C._distributed_c10d._dump_nccl_trace = boom
    r = CommStatsReporter(lambda *a: published.append(a), 0.01)
    r.maybe_start()
    _wait_for(lambda: not r._thread.is_alive())

    r.maybe_start()
    r.stop()
    assert published == []


def test_is_initialized_failure_never_raises(monkeypatch, reporter, published):
    def boom():
        raise RuntimeError("broken")

    fake = _FakeTorch()
    fake.distributed.is_initialized = boom
    monkeypatch.setitem(sys.modules, "torch", fake)

    reporter.maybe_start()
    reporter.clock.t += 120
    reporter.maybe_start()

    assert published == []
    assert reporter._thread is None


@pytest.mark.parametrize("n", [2_000, 20_000])
def test_read_cost(torch, published, n):
    torch.entries = [
        _entry(i + 1, duration=1.0, sizes=((1024,),), dtypes=("BFloat16",))
        for i in range(n)
    ]
    r = CommStatsReporter(lambda *a: published.append(a), 60.0)

    t0 = time.perf_counter()
    r.report()
    cost = time.perf_counter() - t0

    assert published[0][1][0].count == n
    print(f"comm_stats read of {n} entries: {cost * 1000:.1f} ms")


def test_exception_disables(torch, reporter, published):
    def boom(**kwargs):
        raise RuntimeError("dump failed")

    torch._C._distributed_c10d._dump_nccl_trace = boom
    reporter.report()
    torch._C._distributed_c10d._dump_nccl_trace = torch._dump
    reporter.clock.t += 120
    reporter.report()

    assert published == []
    assert torch.dump_calls == 0


def test_publish_exception_disables(torch, published):
    calls = []

    def publish(status, colls, n_lost):
        calls.append(status)
        raise RuntimeError("closed")

    clock = _Clock()
    r = CommStatsReporter(publish, 60.0, clock=clock)
    r.report()
    clock.t += 120
    r.report()
    assert calls == ["ok"]
