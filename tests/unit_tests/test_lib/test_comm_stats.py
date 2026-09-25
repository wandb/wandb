from __future__ import annotations

import pickle
import sys
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
def torch(monkeypatch):
    t = _FakeTorch()
    monkeypatch.setitem(sys.modules, "torch", t)
    monkeypatch.setenv("TORCH_NCCL_TRACE_BUFFER_SIZE", "2000")
    return t


@pytest.fixture
def reporter(published):
    clock = _Clock()
    r = CommStatsReporter(
        lambda status, colls: published.append((status, colls)),
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

    reporter.maybe_report()

    assert published == [
        (
            "ok",
            [
                CollectiveSummary("all_gather", 1, 3.0, 3.0, 3.0, 3.0, 48),
                CollectiveSummary("all_reduce", 100, 50.0, 99.0, 100.0, 5050.0, 204800),
                CollectiveSummary("broadcast", 1, 5.0, 5.0, 5.0, 5.0, 128),
            ],
        )
    ]


def test_unknown_dtype_omits_bytes_for_group(torch, reporter, published):
    torch.entries = [
        _entry(1, dtypes=("Float",)),
        _entry(2, dtypes=("ComplexFloat",)),
        _entry(3, name="nccl:broadcast", dtypes=("Long",)),
    ]

    reporter.maybe_report()

    status, colls = published[0]
    assert [(c.name, c.bytes) for c in colls] == [
        ("all_reduce", None),
        ("broadcast", 128),
    ]


def test_dedups_across_dumps_per_process_group(torch, reporter, published):
    torch.entries = [_entry(1, pg=0), _entry(2, pg=0), _entry(1, pg=1)]
    reporter.maybe_report()
    torch.entries += [
        _entry(3, pg=0, duration=7.0),
        _entry(2, pg=1, duration=9.0),
        _entry(4, pg=0, state="scheduled"),
    ]
    reporter.clock.t += 60
    reporter.maybe_report()

    assert published[0][1][0].count == 3
    assert published[1] == (
        "ok",
        [CollectiveSummary("all_reduce", 2, 7.0, 9.0, 9.0, 16.0, 128)],
    )


def test_p2p_seq_tracked_separately(torch, reporter, published):
    torch.entries = [_entry(5), _entry(1, name="nccl:send", p2p=True)]
    reporter.maybe_report()
    torch.entries += [_entry(2, name="nccl:send", p2p=True)]
    reporter.clock.t += 60
    reporter.maybe_report()

    assert [(c.name, c.count) for c in published[0][1]] == [
        ("all_reduce", 1),
        ("send", 1),
    ]
    assert [(c.name, c.count) for c in published[1][1]] == [("send", 1)]


def test_no_new_entries_is_ok_and_empty(torch, reporter, published):
    reporter.maybe_report()
    assert published == [("ok", [])]


def test_no_timing_sends_counts_only(torch, reporter, published):
    torch.entries = [_entry(1, duration=None), _entry(2, duration=None)]

    reporter.maybe_report()

    assert published == [
        ("no_timing", [CollectiveSummary("all_reduce", 2, 0.0, 0.0, 0.0, 0.0, None)])
    ]


def test_falls_back_to_positional_dump_on_type_error(torch, reporter, published):
    def old_dump():
        return pickle.dumps({"entries": [_entry(1)]})

    torch._C._distributed_c10d._dump_nccl_trace = old_dump

    reporter.maybe_report()

    assert published[0][0] == "ok"
    assert published[0][1][0].count == 1


def test_no_torch_is_unavailable(monkeypatch, reporter, published):
    monkeypatch.delitem(sys.modules, "torch", raising=False)
    reporter.maybe_report()
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

    reporter.maybe_report()

    assert published == [("unavailable", [])]
    assert fake.dump_calls == 0


def test_fr_buffer_size_env_alias(monkeypatch, torch, reporter, published):
    monkeypatch.delenv("TORCH_NCCL_TRACE_BUFFER_SIZE")
    monkeypatch.setenv("TORCH_FR_BUFFER_SIZE", "100")
    reporter.maybe_report()
    assert published == [("ok", [])]


def test_rate_limited_by_interval(torch, reporter, published):
    reporter.maybe_report()
    reporter.clock.t += 59
    reporter.maybe_report()
    assert torch.dump_calls == 1

    reporter.clock.t += 1
    reporter.maybe_report()
    assert torch.dump_calls == 2
    assert len(published) == 2


@pytest.mark.parametrize("interval", [None, 0.0, -5.0])
def test_non_positive_interval_uses_60s(torch, published, interval):
    clock = _Clock()
    r = CommStatsReporter(lambda *a: published.append(a), interval, clock=clock)
    r.maybe_report()
    clock.t += 59
    r.maybe_report()
    clock.t += 1
    r.maybe_report()
    assert torch.dump_calls == 2


def test_exception_disables(torch, reporter, published):
    def boom(**kwargs):
        raise RuntimeError("dump failed")

    torch._C._distributed_c10d._dump_nccl_trace = boom
    reporter.maybe_report()
    torch._C._distributed_c10d._dump_nccl_trace = torch._dump
    reporter.clock.t += 120
    reporter.maybe_report()

    assert published == []
    assert torch.dump_calls == 0


def test_publish_exception_disables(torch, published):
    calls = []

    def publish(status, colls):
        calls.append(status)
        raise RuntimeError("closed")

    clock = _Clock()
    r = CommStatsReporter(publish, 60.0, clock=clock)
    r.maybe_report()
    clock.t += 120
    r.maybe_report()
    assert calls == ["ok"]
