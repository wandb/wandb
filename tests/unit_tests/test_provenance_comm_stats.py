from __future__ import annotations

import pickle
import sys
import threading
import time
import types

import pytest
from wandb.sdk.provenance.comm_stats import (
    CollectiveSummary,
    CommStatsReporter,
    fr_buffer_setting,
)


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

    def __init__(
        self, *, initialized=True, has_dump=True, backends=(("cuda", "nccl"),)
    ):
        self.entries: list[dict] = []
        self.pg_config = {"0": {"name": "0", "desc": "default_pg", "ranks": "[0, 1]"}}
        self.dump_calls = 0
        self.dump_threads: list[threading.Thread] = []
        self.dump_times: list[float] = []
        names = dict(backends)
        pg = types.SimpleNamespace(
            _device_types=[types.SimpleNamespace(type=d) for d in names],
            _get_backend=lambda d: types.SimpleNamespace(name=lambda: names[d.type]),
        )
        self.distributed = types.SimpleNamespace(
            is_initialized=lambda: initialized,
            distributed_c10d=types.SimpleNamespace(_get_default_group=lambda: pg),
        )
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
        return pickle.dumps(
            {
                "version": "2.10",
                "pg_config": dict(self.pg_config),
                "entries": list(self.entries),
            }
        )


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
    monkeypatch.delenv("TORCH_FR_BUFFER_SIZE", raising=False)
    monkeypatch.setenv("TORCH_NCCL_TRACE_BUFFER_SIZE", "2000")
    return t


@pytest.fixture
def read_log():
    return []


@pytest.fixture
def reporter(published, lost, read_log):
    clock = _Clock()
    wall = iter(range(5_000_000_000, 10**12, 60_000_000_000))

    def publish(status, colls, n_lost, read):
        published.append((status, colls))
        lost.append(n_lost)
        read_log.append(read)

    r = CommStatsReporter(
        publish,
        interval=60.0,
        clock=clock,
        wall_clock=lambda: next(wall),
    )
    r.clock = clock
    return r


def test_dump_byte_budget_is_checked_before_unpickling(torch, reporter, monkeypatch):
    from unittest.mock import MagicMock

    loads = MagicMock(side_effect=AssertionError("must not unpickle"))
    monkeypatch.setattr(pickle, "loads", loads)
    torch._C._distributed_c10d._dump_nccl_trace = lambda **kwargs: (
        b"x" * ((32 << 20) + 1)
    )
    reporter.report()
    assert loads.call_count == 0
    assert reporter._disabled


def test_unknown_collective_names_are_counted_as_other_without_the_name(
    torch, reporter, published
):
    torch.entries = [_entry(1, name="private-training-host")]
    reporter.report()
    status, collectives = published[-1]
    assert status == "no_recognized_collectives"
    assert [(c.name, c.count) for c in collectives] == [("other", 1)]
    assert "private" not in repr(published)


def test_fsdp2_collective_names_map_to_families(torch, reporter, published):
    names = [
        "nccl:all_gather_into_tensor_coalesced",
        "nccl:reduce_scatter_tensor_coalesced",
        "nccl:_allgather_base",
        "nccl:_reduce_scatter_base",
        "nccl:all_reduce_coalesced",
        "nccl:allreduce",
        "nccl:broadcast",
        "nccl:all_to_all_single",
        "nccl:send 0->1",
        "nccl:recv 1<-0",
        "nccl:barrier",
        "nccl:coalesced",
    ]
    torch.entries = [_entry(i + 1, name=name) for i, name in enumerate(names)]
    reporter.report()
    status, collectives = published[-1]
    assert status == "ok"
    assert {c.name: c.count for c in collectives} == {
        "all_gather": 2,
        "reduce_scatter": 2,
        "all_reduce": 2,
        "broadcast": 1,
        "all_to_all": 1,
        "send": 1,
        "recv": 1,
        "barrier": 1,
        "other": 1,
    }


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


def test_an_empty_recorder_is_reported(torch, reporter, published):
    reporter.report()
    assert published == [("recorder_empty", [])]


def test_a_recorder_no_group_feeds_is_detached_not_empty(torch, reporter, published):
    torch.pg_config = {}
    reporter.report()
    assert published == [("recorder_detached", [])]


def test_entries_that_never_completed_are_pending_not_ok(torch, reporter, published):
    torch.entries = [_entry(1, state="scheduled"), _entry(2, state="started")]
    reporter.report()
    torch.entries.append(_entry(3))
    reporter.clock.t += 60
    reporter.report()
    torch.entries.append(_entry(4, state="scheduled"))
    reporter.clock.t += 60
    reporter.report()
    assert [status for status, _ in published] == [
        "no_completed_collectives",
        "ok",
        "ok",
    ]


def test_no_new_entries_is_ok_and_empty(torch, reporter, published):
    torch.entries = [_entry(1)]
    reporter.report()
    reporter.clock.t += 120
    reporter.report()
    assert published[-1] == ("ok", [])


def test_no_timing_sends_counts_and_known_bytes(torch, reporter, published):
    torch.entries = [_entry(1, duration=None), _entry(2, duration=None)]

    reporter.report()

    assert published == [
        (
            "no_timing",
            [CollectiveSummary("all_reduce", 2, 0, None, None, None, None, 128)],
        )
    ]


def test_an_untimed_all_reduce_keeps_its_known_bytes(torch, reporter, published):
    torch.entries = [_entry(1, duration=None, sizes=((4, 4),), dtypes=("Float",))]
    reporter.report()
    assert published[0][1][0].bytes == 64


def test_a_collective_pending_while_a_later_one_completes_is_counted_once(
    torch, reporter, published, lost
):
    torch.entries = [_entry(2, state="started"), _entry(3)]
    reporter.report()
    torch.entries = [_entry(2), _entry(3)]
    reporter.clock.t += 60
    reporter.report()
    reporter.clock.t += 60
    reporter.report()

    assert [sum(c.count for c in colls) for _, colls in published] == [1, 1, 0]
    assert lost == [0, 0, 0]


def test_a_pending_collective_evicted_before_completing_is_lost(
    torch, reporter, published, lost
):
    torch.entries = [_entry(1), _entry(2, state="started"), _entry(3)]
    reporter.report()
    # 2 and 4 leave the ring before a read sees them completed.
    torch.entries = [_entry(5), _entry(6)]
    reporter.clock.t += 60
    reporter.report()

    assert [sum(c.count for c in colls) for _, colls in published] == [2, 2]
    assert lost == [0, 2]


def test_duplicate_entries_of_one_sequence_count_once(torch, reporter, published):
    torch.entries = [
        _entry(1, name="nccl:send", p2p=True, state="scheduled"),
        _entry(1, name="nccl:coalesced", p2p=True),
        _entry(1, name="nccl:coalesced", p2p=True),
    ]
    reporter.report()
    torch.entries.append(_entry(2, name="nccl:send", p2p=True, state="scheduled"))
    reporter.clock.t += 60
    reporter.report()

    assert [(c.name, c.count) for c in published[0][1]] == [("other", 1)]
    assert published[1][1] == []


def test_pending_identities_are_bounded_and_overflow_is_lost(
    torch, reporter, published, lost
):
    torch.entries = [_entry(i, state="started") for i in range(1, 1101)]
    torch.entries.append(_entry(1101))
    reporter.report()
    torch.entries = [_entry(i) for i in range(1, 1102)]
    reporter.clock.t += 60
    reporter.report()

    assert lost == [76, 0]
    assert published[1][1][0].count == 1024


def test_every_read_has_an_identity_and_the_interval_since_the_last_read(
    torch, reporter, published, read_log
):
    torch.entries = [_entry(1)]
    reporter.report()
    reporter.clock.t += 60
    reporter.report()
    torch.pg_config = {}
    torch.entries = []
    reporter.clock.t += 60
    reporter.report()

    assert [(r.read_id, r.start_ns, r.end_ns) for r in read_log] == [
        (1, None, 5_000_000_000),
        (2, 5_000_000_000, 65_000_000_000),
        (3, 65_000_000_000, 125_000_000_000),
    ]
    assert all(r.dump_bytes > 0 and r.cpu_ns >= 0 for r in read_log)


def test_statuses_without_a_read_carry_no_read(monkeypatch, reporter, read_log):
    monkeypatch.delitem(sys.modules, "torch", raising=False)
    reporter.report()
    assert read_log == [None]


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


def test_unsupported_dump_signature_disables_without_stack_fallback(
    torch, reporter, published
):
    def old_dump():
        return pickle.dumps({"entries": [_entry(1)]})

    torch._C._distributed_c10d._dump_nccl_trace = old_dump

    reporter.report()

    assert published == [("unavailable", [])]
    assert reporter._disabled


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
        (_FakeTorch(), "0"),
        (_FakeTorch(), "-1"),
        (_FakeTorch(), "lots"),
    ],
    ids=["not_initialized", "no_dump_function", "env_zero", "env_neg", "env_junk"],
)
def test_unavailable(monkeypatch, reporter, published, fake, env):
    monkeypatch.setitem(sys.modules, "torch", fake)
    monkeypatch.delenv("TORCH_FR_BUFFER_SIZE", raising=False)
    monkeypatch.setenv("TORCH_NCCL_TRACE_BUFFER_SIZE", env)

    reporter.report()

    assert published == [("unavailable", [])]
    assert fake.dump_calls == 0


def test_unset_buffer_reads_with_the_torch_default(
    monkeypatch, torch, reporter, published
):
    monkeypatch.delenv("TORCH_NCCL_TRACE_BUFFER_SIZE")
    torch.entries = [_entry(1)]
    reporter.report()
    assert published[-1][0] == "ok"


@pytest.mark.parametrize(
    "fr, trace, expected",
    [
        ("20000", "2000", ("TORCH_FR_BUFFER_SIZE", 20000)),
        (None, "100", ("TORCH_NCCL_TRACE_BUFFER_SIZE", 100)),
        ("", "100", ("TORCH_NCCL_TRACE_BUFFER_SIZE", 100)),
        ("0", "2000", ("TORCH_FR_BUFFER_SIZE", 0)),
        ("x", None, ("TORCH_FR_BUFFER_SIZE", 0)),
        (None, None, (None, 2000)),
    ],
)
def test_buffer_setting_follows_torch_precedence(monkeypatch, fr, trace, expected):
    for name, value in (
        ("TORCH_FR_BUFFER_SIZE", fr),
        ("TORCH_NCCL_TRACE_BUFFER_SIZE", trace),
    ):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    assert fr_buffer_setting() == expected


def test_fr_buffer_size_env_alias(monkeypatch, torch, reporter, published):
    monkeypatch.delenv("TORCH_NCCL_TRACE_BUFFER_SIZE")
    monkeypatch.setenv("TORCH_FR_BUFFER_SIZE", "100")
    torch.entries = [_entry(1)]
    reporter.report()
    assert published[-1][0] == "ok"


@pytest.mark.parametrize(
    "name", ["TORCH_FR_BUFFER_SIZE", "TORCH_NCCL_TRACE_BUFFER_SIZE"]
)
@pytest.mark.parametrize("size, reads", [("20000", 2), ("20001", 0), ("50000", 0)])
def test_buffer_size_in_effect_is_bounded_and_never_refused_silently(
    monkeypatch, torch, reporter, published, lost, name, size, reads
):
    monkeypatch.delenv("TORCH_NCCL_TRACE_BUFFER_SIZE")
    monkeypatch.setenv(name, size)
    torch.entries = [_entry(1)]

    reporter.report()
    reporter.clock.t += 120
    reporter.report()

    assert torch.dump_calls == reads
    if reads:
        assert published[0][0] == "ok"
    else:
        assert published == [("buffer_too_large", [])]
        assert lost == [int(size)]


def test_torchtitan_fr_size_wins_over_the_bootstrap_default(
    monkeypatch, torch, reporter, published
):
    monkeypatch.setenv("TORCH_NCCL_TRACE_BUFFER_SIZE", "2000")
    monkeypatch.setenv("TORCH_FR_BUFFER_SIZE", "50000")
    reporter.report()
    assert published == [("buffer_too_large", [])]
    assert torch.dump_calls == 0


def _cpu_costs(monkeypatch, *costs_ms):
    from wandb.sdk.provenance import comm_stats

    ticks = iter(t for ms in costs_ms for t in (0, ms * 1_000_000))
    monkeypatch.setattr(comm_stats.time, "thread_time_ns", lambda: next(ticks))


def _primed(reporter, torch):
    # The first read has no entry rate, so backoff starts from the second.
    torch.entries = [_entry(1)]
    reporter.report()
    reporter.clock.t += 60


def test_an_over_budget_read_backs_off_instead_of_disabling(
    monkeypatch, torch, reporter, published, read_log
):
    _cpu_costs(monkeypatch, 10, 300)
    _primed(reporter, torch)
    reporter.report()
    assert [status for status, _ in published] == ["ok", "ok"]
    assert read_log[1].cpu_ns == 300_000_000
    assert read_log[1].backoff_s == 120
    assert not read_log[1].over_budget
    assert not reporter._disabled


@pytest.mark.parametrize(
    ("cost_ms", "backoff_s"),
    [(250, None), (251, 120), (500, 120), (501, 240), (1000, 240)],
)
def test_backoff_doubles_the_interval_until_the_read_fits_its_share(
    monkeypatch, torch, reporter, read_log, cost_ms, backoff_s
):
    _cpu_costs(monkeypatch, 10, cost_ms)
    _primed(reporter, torch)
    reporter.report()
    assert read_log[1].backoff_s == backoff_s
    assert not reporter._disabled


def test_a_read_over_the_capped_share_publishes_then_self_disables(
    monkeypatch, torch, reporter, published, lost, read_log
):
    _cpu_costs(monkeypatch, 1001)
    torch.entries = [_entry(1)]
    reporter.report()
    assert [status for status, _ in published] == ["ok", "cpu_budget"]
    assert lost[-1] == 1001
    assert read_log[0].backoff_s is None
    assert reporter._disabled


def test_backed_off_reader_waits_the_longer_interval(monkeypatch, torch, reporter):
    _cpu_costs(monkeypatch, 10, 600, 10)
    _primed(reporter, torch)
    reporter.report()
    reporter.clock.t += 239
    reporter.report()
    assert torch.dump_calls == 2
    reporter.clock.t += 1
    reporter.report()
    assert torch.dump_calls == 3


def test_cheap_reads_recover_the_nominal_interval(
    monkeypatch, torch, reporter, read_log
):
    _cpu_costs(monkeypatch, 10, 300, 100, 10)
    _primed(reporter, torch)
    reporter.report()
    reporter.clock.t += 120
    torch.entries.append(_entry(2))
    reporter.report()
    reporter.clock.t += 60
    reporter.report()
    assert [r.backoff_s for r in read_log] == [None, 120, None, None]
    assert torch.dump_calls == 4


def test_a_backed_off_span_that_overruns_the_ring_is_lost(
    monkeypatch, torch, reporter, published, lost
):
    _cpu_costs(monkeypatch, 10, 600, 10)
    torch.entries = [_entry(s) for s in range(1, 11)]
    reporter.report()
    reporter.clock.t += 60
    reporter.report()
    reporter.clock.t += 240
    # Seqs 11-25 were overwritten while the reader waited.
    torch.entries = [_entry(s) for s in range(26, 36)]
    reporter.report()
    assert lost == [0, 0, 15]
    assert published[-1][1][0].count == 10


def test_backoff_uses_the_reader_thread_wait(monkeypatch, torch, published):
    waits, clock = [], _Clock()
    r = CommStatsReporter(
        lambda *a: published.append(a),
        60.0,
        clock=clock,
        wall_clock=lambda: int(clock.t * 1e9),
    )
    _cpu_costs(monkeypatch, 10, 300, 10)
    torch.entries = [_entry(1)]

    def wait(timeout):
        waits.append(timeout)
        clock.t += timeout
        return len(waits) > 1

    monkeypatch.setattr(r._stop, "wait", wait)
    r._run()
    assert waits == [60, 120]
    assert torch.dump_calls == 3


_NAMES = (
    "nccl2:_all_gather_base",
    "nccl2:_reduce_scatter_base",
    "nccl2:allreduce",
    "nccl2:all_gather_into_tensor_coalesced",
    "nccl2:reduce_scatter_tensor_coalesced",
    "nccl2:broadcast",
    "nccl2:barrier",
    "nccl2:mystery_op",
)


def _synthetic(offset, n=20000):
    entries = []
    for g in range(offset, offset + n):
        p2p = g % 97 == 0
        name = "nccl2:send" if p2p else _NAMES[g % len(_NAMES)]
        e = {
            "pg_id": g % 6,
            "collective_seq_id": 0 if p2p else g // 6 + 1,
            "p2p_seq_id": g if p2p else 0,
            "is_p2p": p2p,
            "profiling_name": name,
            "state": "scheduled" if g >= offset + n - 50 else "completed",
            "input_sizes": [[1024 * (1 + g % 4)], [8, 16]],
            "input_dtypes": [
                "ComplexFloat" if name.endswith("mystery_op") else "BFloat16",
                "Float",
            ],
        }
        if g % 11:
            e["duration_ms"] = (g % 997) * 0.01 + 0.05
        entries.append(e)
        if g % 50 == 0:
            entries.append(dict(e))
    return entries[:n]


# Captured from the reader before the per-key and per-name caches.
_SYNTHETIC_READS = [
    (
        "ok",
        0,
        [
            CollectiveSummary(
                "all_gather",
                4851,
                4411,
                4.95,
                9.920000000000002,
                10.010000000000002,
                21947.72,
                27323904,
            ),
            CollectiveSummary(
                "all_reduce",
                2425,
                2204,
                4.9399999999999995,
                9.920000000000002,
                10.010000000000002,
                10955.550000000001,
                16140800,
            ),
            CollectiveSummary(
                "barrier",
                2426,
                2206,
                4.93,
                9.89,
                10.010000000000002,
                10948.68,
                16147456,
            ),
            CollectiveSummary(
                "broadcast",
                2426,
                2206,
                4.93,
                9.89,
                10.010000000000002,
                10956.48,
                11179008,
            ),
            CollectiveSummary(
                "other",
                2425,
                2204,
                4.9399999999999995,
                9.91,
                10.010000000000002,
                10969.880000000001,
                None,
            ),
            CollectiveSummary(
                "reduce_scatter",
                4851,
                4409,
                4.95,
                9.91,
                10.010000000000002,
                21934.84,
                17384960,
            ),
            CollectiveSummary(
                "send", 203, 184, 5.06, 9.96, 10.010000000000002, 934.11, 1140224
            ),
        ],
    ),
    (
        "ok",
        0,
        [
            CollectiveSummary(
                "all_gather",
                989,
                897,
                5.05,
                9.930000000000001,
                10.010000000000002,
                4524.49,
                5566976,
            ),
            CollectiveSummary(
                "all_reduce",
                495,
                451,
                5.07,
                9.930000000000001,
                10.010000000000002,
                2275.9,
                3294720,
            ),
            CollectiveSummary("barrier", 495, 449, 5.06, 9.91, 9.99, 2263.0, 3294720),
            CollectiveSummary(
                "broadcast", 495, 449, 5.03, 9.9, 10.010000000000002, 2258.09, 2280960
            ),
            CollectiveSummary(
                "other",
                495,
                451,
                5.05,
                9.920000000000002,
                10.000000000000002,
                2279.7000000000003,
                None,
            ),
            CollectiveSummary(
                "reduce_scatter",
                990,
                902,
                5.01,
                9.89,
                10.000000000000002,
                4522.27,
                3548160,
            ),
            CollectiveSummary("send", 41, 37, 5.32, 9.9, 9.9, 189.11, 233984),
        ],
    ),
    (
        "ok",
        48291,
        [
            CollectiveSummary(
                "all_gather",
                4852,
                4410,
                4.99,
                9.9,
                10.010000000000002,
                22037.83,
                27326464,
            ),
            CollectiveSummary(
                "all_reduce",
                2426,
                2207,
                5.0,
                9.89,
                10.010000000000002,
                11030.17,
                16147456,
            ),
            CollectiveSummary(
                "barrier",
                2425,
                2204,
                4.99,
                9.920000000000002,
                10.010000000000002,
                11053.53,
                16140800,
            ),
            CollectiveSummary(
                "broadcast",
                2426,
                2206,
                4.9799999999999995,
                9.920000000000002,
                10.010000000000002,
                11045.470000000001,
                11179008,
            ),
            CollectiveSummary(
                "other",
                2424,
                2204,
                5.0,
                9.920000000000002,
                10.010000000000002,
                11036.07,
                None,
            ),
            CollectiveSummary(
                "reduce_scatter",
                4852,
                4410,
                4.99,
                9.91,
                10.010000000000002,
                22059.09,
                17389568,
            ),
            CollectiveSummary(
                "send",
                202,
                184,
                5.09,
                9.940000000000001,
                10.000000000000002,
                937.88,
                1141760,
            ),
        ],
    ),
]


def test_full_buffer_summaries_match_the_reference_reader(
    monkeypatch, torch, reporter, published, lost
):
    monkeypatch.setenv("TORCH_FR_BUFFER_SIZE", "20000")
    for offset in (0, 4000, 30000):
        torch.entries = _synthetic(offset)
        reporter.report()
        reporter.clock.t += 60
    got = [
        (status, n, colls) for (status, colls), n in zip(published, lost, strict=True)
    ]
    assert got == _SYNTHETIC_READS


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
        _wait_for(lambda: torch.dump_calls == 1)
        time.sleep(0.15)
    finally:
        r.stop()

    assert threading.current_thread() not in torch.dump_threads
    assert len(set(torch.dump_threads)) == 1
    # One read at start, then the final read on stop.
    assert torch.dump_calls == 2
    assert published[0][:3] == (
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
    # The final read on stop is the only one after the thread's.
    assert torch.dump_calls == 2


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
    assert published == [("unavailable", [], 0, None)]


def test_is_initialized_failure_never_raises(monkeypatch, reporter, published):
    def boom():
        raise RuntimeError("broken")

    fake = _FakeTorch()
    fake.distributed.is_initialized = boom
    monkeypatch.setitem(sys.modules, "torch", fake)

    reporter.maybe_start()
    reporter.clock.t += 120
    reporter.maybe_start()

    assert published == [("unavailable", [])]
    assert reporter._thread is None


@pytest.mark.parametrize("n", [2_000, 5_000])
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

    assert published == [("unavailable", [])]
    assert torch.dump_calls == 0


def test_publish_exception_disables(torch, published):
    calls = []

    def publish(status, colls, n_lost, read):
        calls.append(status)
        raise RuntimeError("closed")

    clock = _Clock()
    torch.entries = [_entry(1)]
    r = CommStatsReporter(publish, 60.0, clock=clock)
    r.report()
    clock.t += 120
    r.report()
    assert calls == ["ok"]


def test_reads_the_nccl_recorder_through_the_renamed_dump(torch, reporter, published):
    c10d = torch._C._distributed_c10d
    del c10d._dump_nccl_trace
    backends = []

    def dump_fr_trace(includeCollectives, includeStackTraces, onlyActive, backend):  # noqa: N803
        """_dump_fr_trace(includeCollectives, ..., backend: str = 'gloo') -> bytes"""
        backends.append(backend)
        return torch._dump(includeCollectives, includeStackTraces, onlyActive)

    c10d._dump_fr_trace = dump_fr_trace
    torch.entries = [_entry(1)]
    reporter.report()
    assert backends == ["nccl"]
    assert published[-1][0] == "ok"
    assert [c.name for c in published[-1][1]] == ["all_reduce"]


def test_generic_dump_without_backend_falls_back_to_the_nccl_dump(
    torch, reporter, published
):
    c10d = torch._C._distributed_c10d

    def dump_fr_trace(includeCollectives, includeStackTraces, onlyActive):  # noqa: N803
        """_dump_fr_trace(includeCollectives, includeStackTraces, onlyActive) -> bytes"""
        raise AssertionError("the generic dump holds only the gloo recorder")

    c10d._dump_fr_trace = dump_fr_trace
    torch.entries = [_entry(1)]
    reporter.report()
    assert torch.dump_calls == 1
    assert published[-1][0] == "ok"
    del c10d._dump_nccl_trace
    reporter.clock.t += 120
    reporter.report()
    assert published[-1] == ("unavailable", [])


def test_nccl_dump_wins_over_the_generic_recorder(torch, reporter, published):
    def dump_fr_trace(**kwargs):
        """_dump_fr_trace(..., backend: str = 'gloo') -> bytes"""
        raise AssertionError("backend='nccl' reads an empty CPU-event recorder")

    torch._C._distributed_c10d._dump_fr_trace = dump_fr_trace
    torch.entries = [_entry(1)]
    reporter.report()
    assert torch.dump_calls == 1
    assert published[-1][0] == "ok"


def test_nccl2_reads_the_recorder_its_hook_feeds(torch, reporter, published):
    backends = []

    def nccl_dump(**kwargs):
        raise AssertionError("nccl2 never writes to the CUDA-event recorder")

    def dump_fr_trace(includeCollectives, includeStackTraces, onlyActive, backend):  # noqa: N803
        """_dump_fr_trace(includeCollectives, ..., backend: str = 'gloo') -> bytes"""
        backends.append(backend)
        return torch._dump(includeCollectives, includeStackTraces, onlyActive)

    torch.distributed = _FakeTorch(
        backends=(("cpu", "gloo"), ("cuda", "nccl2"))
    ).distributed
    torch._C._distributed_c10d._dump_nccl_trace = nccl_dump
    torch._C._distributed_c10d._dump_fr_trace = dump_fr_trace
    torch.entries = [_entry(1, name="nccl2:_reduce_scatter_base")]
    reporter.report()
    assert backends == ["nccl2"]
    assert published[-1][0] == "ok"
    assert [c.name for c in published[-1][1]] == ["reduce_scatter"]


def test_nccl2_without_the_generic_dump_is_unavailable(torch, reporter, published):
    torch.distributed = _FakeTorch(backends=(("cuda", "nccl2"),)).distributed
    torch.entries = [_entry(1)]
    reporter.report()
    assert published == [("unavailable", [])]
    assert torch.dump_calls == 0


class _Ring:
    """A 20000-entry recorder fed at a fixed rate on a simulated clock."""

    def __init__(self, torch, clock, per_minute, size=20000):
        self.torch, self.clock, self.per_minute, self.size = (
            torch,
            clock,
            per_minute,
            size,
        )
        self.start = clock.t

    def fill(self):
        produced = int((self.clock.t - self.start) * self.per_minute / 60)
        first = max(1, produced - self.size + 1)
        self.torch.entries = [_entry(s) for s in range(first, produced + 1)]


def _simulated(monkeypatch, torch, cost_ms, per_minute, minutes):
    from wandb.sdk.provenance import comm_stats

    monkeypatch.setenv("TORCH_FR_BUFFER_SIZE", "20000")
    clock, reads, lost = _Clock(), [], []
    ring = _Ring(torch, clock, per_minute)
    r = CommStatsReporter(
        lambda status, colls, n, read: (reads.append(read), lost.append(n)),
        60.0,
        clock=clock,
        wall_clock=lambda: int(clock.t * 1e9),
    )
    ticks = iter(t for _ in range(10**6) for t in (0, cost_ms * 1_000_000))
    monkeypatch.setattr(comm_stats.time, "thread_time_ns", lambda: next(ticks))
    end = clock.t + minutes * 60
    while clock.t < end:
        clock.t += 1
        if r._last_read is None or clock.t - r._last_read >= r._wait:
            ring.fill()
            r.report()
    return r, [x for x in reads if x is not None], lost


def test_the_interval_is_capped_so_the_ring_holds_a_window(monkeypatch, torch):
    _, reads, lost = _simulated(monkeypatch, torch, 600, 4600, 30)
    gaps = [(b.end_ns - a.end_ns) / 1e9 for a, b in zip(reads, reads[1:], strict=False)]
    assert max(gaps) <= 0.8 * 20000 / (4600 / 60) + 1
    assert max(gaps) > 120
    assert sum(lost) == 0
    # 600 ms per 208 s is still within 250 ms per 60 s.
    assert not any(r.over_budget for r in reads[1:])


def test_a_ring_too_small_for_the_cpu_share_is_read_over_budget(monkeypatch, torch):
    _, reads, lost = _simulated(monkeypatch, torch, 600, 12000, 20)
    gaps = [(b.end_ns - a.end_ns) / 1e9 for a, b in zip(reads, reads[1:], strict=False)]
    assert max(gaps) <= 0.8 * 20000 / (12000 / 60) + 1
    assert all(r.over_budget for r in reads)
    assert sum(lost) == 0


def test_a_slow_rate_keeps_the_cpu_backoff(monkeypatch, torch):
    _, reads, lost = _simulated(monkeypatch, torch, 600, 1000, 30)
    assert {r.backoff_s for r in reads[1:]} == {240}
    assert not any(r.over_budget for r in reads[1:])
    assert sum(lost) == 0


def test_the_first_read_has_no_rate_and_stays_nominal(
    monkeypatch, torch, reporter, read_log
):
    _cpu_costs(monkeypatch, 600)
    torch.entries = [_entry(s) for s in range(1, 100)]
    reporter.report()
    assert read_log[0].backoff_s is None
    assert read_log[0].over_budget


def test_stop_reads_the_tail_once_regardless_of_backoff(monkeypatch, torch, published):
    r = CommStatsReporter(lambda *a: published.append(a), 60.0)
    _cpu_costs(monkeypatch, 600, 10)
    torch.entries = [_entry(1)]
    r.maybe_start()
    _wait_for(lambda: torch.dump_calls == 1)
    torch.entries.append(_entry(2))
    r.stop()
    assert torch.dump_calls == 2
    assert len(set(torch.dump_threads)) == 1
    assert threading.current_thread() not in torch.dump_threads
    assert published[-1][1] == [
        CollectiveSummary("all_reduce", 1, 1, 1.0, 1.0, 1.0, 1.0, 64)
    ]
    r.stop()
    assert torch.dump_calls == 2


def test_stop_skips_the_final_read_once_the_group_is_gone(torch, published):
    r = CommStatsReporter(lambda *a: published.append(a), 60.0)
    torch.entries = [_entry(1)]
    r.maybe_start()
    _wait_for(lambda: torch.dump_calls == 1)
    torch.distributed.is_initialized = lambda: False
    r.stop()
    assert torch.dump_calls == 1
    assert [p[0] for p in published] == ["ok"]


def test_stop_skips_the_final_read_when_self_disabled(monkeypatch, torch, published):
    r = CommStatsReporter(lambda *a: published.append(a), 60.0)
    _cpu_costs(monkeypatch, 1001)
    torch.entries = [_entry(1)]
    r.maybe_start()
    _wait_for(lambda: not r._thread.is_alive())
    r.stop()
    assert torch.dump_calls == 1


def test_stop_without_a_reader_thread_reads_nothing(torch, published):
    CommStatsReporter(lambda *a: published.append(a), 60.0).stop()
    assert torch.dump_calls == 0
