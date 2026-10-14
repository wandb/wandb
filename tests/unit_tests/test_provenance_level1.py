import os
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize(
    "key", ["TORCH_NCCL_TRACE_BUFFER_SIZE", "TORCH_FR_BUFFER_SIZE"]
)
def test_explicit_zero_is_not_overwritten(monkeypatch, key):
    from wandb.sdk.provenance.level1 import install_level1_bootstrap

    monkeypatch.delenv("TORCH_NCCL_TRACE_BUFFER_SIZE", raising=False)
    monkeypatch.delenv("TORCH_FR_BUFFER_SIZE", raising=False)
    monkeypatch.setenv(key, "0")
    install_level1_bootstrap()
    assert os.environ[key] == "0"
    assert (
        "TORCH_NCCL_TRACE_BUFFER_SIZE" not in os.environ
        or os.environ["TORCH_NCCL_TRACE_BUFFER_SIZE"] == "0"
    )


def test_unset_buffer_is_set_under_the_name_torch_reads_first(monkeypatch):
    from wandb.sdk.provenance.level1 import install_level1_bootstrap

    monkeypatch.delitem(__import__("sys").modules, "torch.distributed", raising=False)
    monkeypatch.delenv("TORCH_NCCL_TRACE_BUFFER_SIZE", raising=False)
    monkeypatch.delenv("TORCH_FR_BUFFER_SIZE", raising=False)
    install_level1_bootstrap()
    assert os.environ["TORCH_FR_BUFFER_SIZE"] == "2000"
    assert "TORCH_NCCL_TRACE_BUFFER_SIZE" not in os.environ


@pytest.mark.parametrize(
    "key", ["TORCH_NCCL_TRACE_BUFFER_SIZE", "TORCH_FR_BUFFER_SIZE"]
)
def test_a_user_buffer_size_is_kept(monkeypatch, key):
    from wandb.sdk.provenance.level1 import install_level1_bootstrap

    monkeypatch.delitem(__import__("sys").modules, "torch.distributed", raising=False)
    monkeypatch.delenv("TORCH_NCCL_TRACE_BUFFER_SIZE", raising=False)
    monkeypatch.delenv("TORCH_FR_BUFFER_SIZE", raising=False)
    monkeypatch.setenv(key, "20000")
    install_level1_bootstrap()
    assert os.environ[key] == "20000"
    assert (
        len({"TORCH_NCCL_TRACE_BUFFER_SIZE", "TORCH_FR_BUFFER_SIZE"} & set(os.environ))
        == 1
    )


def _collector(events, dropped=0, times=None, accounted=None):
    from types import SimpleNamespace

    from wandb.sdk.provenance import level1

    def emit(kind, payload, wall_time_ns=None):
        events.append((kind, payload))
        if times is not None:
            times.append(wall_time_ns)

    collector = level1.Level1Collectors(
        SimpleNamespace(
            emit=emit,
            dropped=dropped,
            account=lambda **kw: None if accounted is None else accounted.append(kw),
        )
    )
    collector._comm = SimpleNamespace(maybe_start=lambda: None, stop=lambda: None)
    collector._transport_started = True
    return collector


def _read(
    read_id,
    start_ns=None,
    end_ns=None,
    cpu_ns=0,
    dump_bytes=0,
    backoff_s=None,
    over_budget=False,
):
    from wandb.sdk.provenance.comm_stats import RecorderRead

    end_ns = read_id * 60_000_000_000 if end_ns is None else end_ns
    return RecorderRead(
        read_id, start_ns, end_ns, cpu_ns, dump_bytes, backoff_s, over_budget
    )


def _engine(parameters):
    from types import SimpleNamespace

    return SimpleNamespace(
        model_parts=[SimpleNamespace(parameters=lambda: parameters)], device="cpu"
    )


def test_gradient_scan_samples_a_fixed_tensor_stride_without_host_sync(monkeypatch):
    import math
    from types import SimpleNamespace

    import torch
    from wandb.sdk.provenance import level1

    events = []
    monkeypatch.setattr(level1, "_SCAN_TENSORS", 2)
    monkeypatch.setattr(torch.cuda, "is_initialized", lambda: True)
    monkeypatch.setattr(torch.cuda, "Event", lambda **kwargs: SimpleNamespace())
    monkeypatch.setattr(
        torch.Tensor, "item", lambda self: pytest.fail("per-tensor host sync")
    )
    parameters = [torch.zeros(4, requires_grad=True) for _ in range(4)]
    parameters[0].grad = torch.tensor([3.0, 4.0, 0.0, 0.0])
    parameters[1].grad = torch.full((4,), math.nan)
    parameters[2].grad = torch.tensor([math.inf, 1.0, 1.0, 1.0])
    parameters[3].grad = torch.ones(4)
    collector = _collector(events)
    collector._gemm_disabled = True
    collector.step(_engine(parameters), 100)
    diagnostic = next(p for kind, p in events if kind == "diagnostic" and "norm" in p)
    assert diagnostic["count"] == 2
    assert diagnostic["finite_count"] == 1
    assert diagnostic["nonfinite_count"] == 1
    assert diagnostic["norm"] == pytest.approx(5.0)
    assert (diagnostic["status"], diagnostic["reason"]) == ("partial", "tensor_sample")
    assert (
        "capability",
        {"collector": "gradient_health", "status": "available"},
    ) in events


def test_gradient_budget_breach_disables_only_gradient_health(monkeypatch):
    from types import SimpleNamespace

    import torch
    from wandb.sdk.provenance import level1

    events = []
    clock = iter(range(0, 10**12, 30_000_000))
    monkeypatch.setattr(level1.time, "thread_time_ns", lambda: next(clock))
    monkeypatch.setattr(torch.cuda, "is_initialized", lambda: True)
    monkeypatch.setattr(torch.cuda, "Event", lambda **kwargs: SimpleNamespace())
    parameter = torch.zeros(4, requires_grad=True)
    parameter.grad = torch.ones(4)
    collector = _collector(events)
    gemms = []
    collector._timing = SimpleNamespace(
        completed=lambda: [],
        start=lambda phase, step: gemms.append(step),
        finish=lambda token: None,
        close=lambda: None,
    )
    collector._tensors = (torch.ones(2, 2), torch.ones(2, 2), torch.ones(2, 2))
    for step in (100, 200, 300):
        collector.step(_engine([parameter]), step)
    capabilities = [
        (p["collector"], p["status"], p.get("reason"))
        for kind, p in events
        if kind == "capability"
    ]
    assert ("gradient_health", "self_disabled", "cpu_budget") in capabilities
    assert not any(c[0] == "active_diagnostics" for c in capabilities)
    assert gemms == [100, 200, 300]
    assert (
        len(
            [
                p
                for kind, p in events
                if p.get("collector") == "gradient_health" and kind == "diagnostic"
            ]
        )
        == 2
    )


def test_level1_enables_nccl_timing_unless_the_user_set_it(monkeypatch):
    from wandb.sdk.provenance.level1 import install_level1_bootstrap

    monkeypatch.delitem(__import__("sys").modules, "torch.distributed", raising=False)
    monkeypatch.delenv("TORCH_NCCL_ENABLE_TIMING", raising=False)
    install_level1_bootstrap()
    assert os.environ["TORCH_NCCL_ENABLE_TIMING"] == "1"
    monkeypatch.setenv("TORCH_NCCL_ENABLE_TIMING", "0")
    install_level1_bootstrap()
    assert os.environ["TORCH_NCCL_ENABLE_TIMING"] == "0"


def test_flight_recorder_reports_available_after_unavailable():
    events = []
    collector = _collector(events)
    from wandb.sdk.provenance.comm_stats import CollectiveSummary

    def summary(name):
        return CollectiveSummary(name, 3, 3, 1.0, 1.0, 1.0, 3.0, 64)

    collector._communication("unavailable", [], 0, None)
    for read_id, (status, collectives) in enumerate(
        [
            ("recorder_detached", []),
            ("recorder_detached", []),
            ("recorder_empty", []),
            ("no_completed_collectives", []),
            ("no_recognized_collectives", [summary("other")]),
            ("ok", []),
            ("ok", [summary("all_gather")]),
            ("ok", [summary("all_gather")]),
            ("no_timing", [summary("all_gather")]),
        ],
        start=1,
    ):
        collector._communication(status, collectives, 0, _read(read_id))
    # Every read reports the recorder state; a bare ok read keeps the last one.
    assert [
        (p["status"], p.get("reason"), p.get("count"), p.get("read_id"))
        for kind, p in events
        if p.get("collector") == "flight_recorder"
    ] == [
        ("unavailable", "recorder_unavailable", None, None),
        ("partial", "recorder_detached", None, 1),
        ("partial", "recorder_detached", None, 2),
        ("partial", "recorder_empty", None, 3),
        ("partial", "no_completed_collectives", None, 4),
        ("partial", "no_recognized_collectives", 3, 5),
        ("partial", "no_recognized_collectives", 0, 6),
        ("available", None, None, 7),
        ("available", None, None, 8),
        ("partial", "no_timing", None, 9),
    ]
    assert [p["collective"] for kind, p in events if kind == "communication"] == [
        "other",
        "all_gather",
        "all_gather",
        "all_gather",
    ]


def test_gemm_warms_up_untimed_before_the_first_timed_probe(monkeypatch):
    from types import SimpleNamespace

    import torch

    events, calls = [], []
    monkeypatch.setattr(torch.cuda, "is_initialized", lambda: True)
    monkeypatch.setattr(
        torch.cuda,
        "Event",
        lambda **kwargs: SimpleNamespace(record=lambda: calls.append("event")),
    )
    monkeypatch.setattr(torch, "mm", lambda *args, **kwargs: calls.append("mm"))
    collector = _collector(events)
    collector.step(_engine([]), 100)
    assert calls == ["mm", "event", "mm", "event"]


def test_flight_recorder_records_from_any_backend_recorder_are_available(
    monkeypatch,
):
    import sys
    from types import SimpleNamespace

    torch = SimpleNamespace(_C=SimpleNamespace(_distributed_c10d=SimpleNamespace()))
    monkeypatch.setitem(sys.modules, "torch", torch)
    events = []
    from wandb.sdk.provenance.comm_stats import CollectiveSummary

    summary = CollectiveSummary("all_gather", 1, 1, 1.0, 1.0, 1.0, 1.0, 64)
    _collector(events)._communication("ok", [summary], 0, _read(1))
    assert events[-2][1] == {
        "collector": "flight_recorder",
        "status": "available",
        "lost_count": 0,
        "read_id": 1,
        "window_end_unix_ms": 60_000,
    }


def test_flight_recorder_bound_reasons_carry_the_size():
    events = []
    collector = _collector(events)
    collector._communication("buffer_too_large", [], 50000, None)
    collector._communication("cpu_budget", [], 300, None)
    assert [p for kind, p in events if p.get("collector") == "flight_recorder"] == [
        {
            "collector": "flight_recorder",
            "status": "partial",
            "reason": "buffer_too_large",
            "count": 50000,
        },
        {
            "collector": "flight_recorder",
            "status": "self_disabled",
            "reason": "cpu_budget",
            "count": 300,
        },
    ]


def test_a_backed_off_reader_is_partial_until_reads_are_cheap_again():
    from wandb.sdk.provenance.comm_stats import CollectiveSummary

    events = []
    collector = _collector(events)
    summary = CollectiveSummary("all_gather", 1, 1, 1.0, 1.0, 1.0, 1.0, 64)
    collector._communication("ok", [summary], 0, _read(1, backoff_s=120.0))
    collector._communication("ok", [summary], 3, _read(2, backoff_s=240.0))
    collector._communication("no_recognized_collectives", [], 0, _read(3))
    collector._communication("ok", [summary], 0, _read(4, backoff_s=120.0))
    collector._communication("ok", [summary], 0, _read(5))
    assert [
        (p["status"], p.get("reason"), p.get("interval_s"), p.get("count"))
        for _, p in events
        if p.get("collector") == "flight_recorder"
    ] == [
        ("partial", "backed_off", 120.0, None),
        ("partial", "backed_off", 240.0, None),
        ("partial", "no_recognized_collectives", None, 0),
        ("partial", "backed_off", 120.0, None),
        ("available", None, None, None),
    ]
    assert [kind for kind, _ in events].count("communication") == 4


def test_one_read_shares_its_identity_and_reports_loss_once():
    from wandb.sdk.provenance.comm_stats import CollectiveSummary

    events, times = [], []
    collector = _collector(events, times=times)
    events.clear()
    times.clear()
    read = _read(2, start_ns=60_000_000_123, end_ns=120_000_456_789)
    collector._communication(
        "ok",
        [
            CollectiveSummary("all_gather", 3, 3, 1.0, 2.0, 2.0, 4.0, 64),
            CollectiveSummary("all_reduce", 5, 5, 1.0, 1.0, 1.0, 5.0, 32),
        ],
        10,
        read,
    )
    window = {
        "read_id": 2,
        "window_start_unix_ms": 60_000,
        "window_end_unix_ms": 120_000,
    }
    assert all(window.items() <= p.items() for _, p in events)
    assert [p.get("lost_count") for _, p in events] == [10, None, None]
    assert times == [120_000_456_789] * 3


def test_a_read_without_new_collectives_still_reports_its_loss():
    from wandb.sdk.provenance.comm_stats import CollectiveSummary

    events = []
    collector = _collector(events)
    summary = CollectiveSummary("all_gather", 1, 1, 1.0, 1.0, 1.0, 1.0, 64)
    collector._communication("ok", [summary], 0, _read(1))
    collector._communication("ok", [], 7, _read(2, start_ns=60_000_000_000))
    assert events[-1] == (
        "capability",
        {
            "collector": "flight_recorder",
            "status": "available",
            "lost_count": 7,
            "read_id": 2,
            "window_start_unix_ms": 60_000,
            "window_end_unix_ms": 120_000,
        },
    )
    assert [kind for kind, _ in events].count("communication") == 1


def test_recorder_read_cost_is_charged_to_the_collector():
    accounted = []
    collector = _collector([], accounted=accounted)
    collector._communication(
        "recorder_empty", [], 0, _read(1, cpu_ns=17, dump_bytes=4096)
    )
    assert accounted == [{"cpu_ns": 17, "transient_bytes": 4096}]


class _Group:
    def __init__(self, *devices, fail=False):
        self._device_types = [SimpleNamespace(type=d) for d in devices or ("cuda",)]
        self.hooks = {}
        self.registrations = 0
        self.fail = fail

    def register_pre_hook(self, hook_id, hook):
        if self.fail:
            raise RuntimeError("no hooks")
        self.hooks[hook_id] = hook
        self.registrations += 1

    def unregister_pre_hook(self, hook_id):
        self.hooks.pop(hook_id, None)

    def fire(self, name, *nbytes):
        tensors = [
            SimpleNamespace(numel=lambda n=n: n, element_size=lambda: 2) for n in nbytes
        ]
        for hook in list(self.hooks.values()):
            hook(
                SimpleNamespace(name=SimpleNamespace(name=name), input_tensors=tensors)
            )


@pytest.fixture
def graphs(monkeypatch):
    import sys

    state = SimpleNamespace(
        capturing=False,
        wrappers=[],
        dp=_Group("cuda", "cpu"),
        tp=_Group("cuda"),
        cpu=_Group("cpu"),
    )
    groups = {state.dp: 0, state.tp: 1, state.cpu: 2}
    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(
            cuda=SimpleNamespace(
                is_current_stream_capturing=lambda: state.capturing,
                is_initialized=lambda: False,
            ),
            distributed=SimpleNamespace(
                distributed_c10d=SimpleNamespace(_world=SimpleNamespace(pg_map=groups))
            ),
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "torchtitan.distributed.cuda_graph",
        SimpleNamespace(_manager=SimpleNamespace(_wrappers=state.wrappers)),
    )
    return state


def _schedules(events):
    return [p for kind, p in events if kind == "communication_schedule"]


def _capture(graphs, wrapper):
    graphs.capturing = True
    graphs.dp.fire("ALLGATHER_BASE", 50)
    graphs.dp.fire("ALLGATHER_BASE", 50)
    graphs.dp.fire("REDUCE_SCATTER_BASE", 200)
    graphs.tp.fire("ALLREDUCE", 4)
    graphs.tp.fire("ALLGATHER_INTO_TENSOR_COALESCED", 25, 25)
    graphs.capturing = False
    wrapper._graph = object()


def test_graph_capture_records_the_collective_schedule_once(graphs):
    events = []
    collector = _collector(events)
    engine = SimpleNamespace(num_accumulation_steps=1)
    wrapper = SimpleNamespace(_graph=None, _warmup_remaining=1)
    collector.before_forward_backward(engine, 1)
    graphs.wrappers.append(wrapper)
    graphs.dp.fire("ALLGATHER_BASE", 50)
    collector.after_forward_backward(engine)
    wrapper._warmup_remaining = 0
    collector.before_forward_backward(engine, 2)
    graphs.dp.fire("ALLGATHER_BASE", 50)
    collector.after_forward_backward(engine)
    collector.before_forward_backward(engine, 3)
    _capture(graphs, wrapper)
    collector.after_forward_backward(engine)
    registrations = graphs.dp.registrations
    for step in range(4, 8):
        collector.before_forward_backward(engine, step)
        collector.after_forward_backward(engine)
    assert graphs.dp.registrations == registrations == 3
    assert not graphs.dp.hooks and not graphs.tp.hooks
    assert graphs.cpu.registrations == 0
    common = {
        "schedule_id": 1,
        "effective_from_step": 3,
        "replays_per_step": 1,
        "source": "cuda_graph_capture",
    }
    assert _schedules(events) == [
        {
            **common,
            "collective": "all_gather",
            "count_per_step": 3,
            "bytes_per_step": 300,
            "group_count": 2,
        },
        {
            **common,
            "collective": "all_reduce",
            "count_per_step": 1,
            "bytes_per_step": 8,
            "group_count": 1,
        },
        {
            **common,
            "collective": "reduce_scatter",
            "count_per_step": 1,
            "bytes_per_step": 400,
            "group_count": 1,
        },
    ]
    assert (
        "capability",
        {
            "collector": "communication_schedule",
            "status": "available",
            "schedule_id": 1,
            "effective_from_step": 3,
        },
    ) in events


def test_a_recapture_replaces_the_schedule_from_its_step(graphs):
    events = []
    collector = _collector(events)
    engine = SimpleNamespace(num_accumulation_steps=1)
    wrapper = SimpleNamespace(_graph=None, _warmup_remaining=0)
    graphs.wrappers.append(wrapper)
    collector.before_forward_backward(engine, 3)
    _capture(graphs, wrapper)
    collector.after_forward_backward(engine)
    graphs.wrappers.clear()
    wrapper._graph = None
    collector.before_forward_backward(engine, 50)
    graphs.capturing = True
    graphs.tp.fire("ALLREDUCE", 4)
    graphs.capturing = False
    wrapper._graph = object()
    collector.after_forward_backward(engine)
    assert [
        (p["schedule_id"], p["effective_from_step"], p["collective"])
        for p in _schedules(events)
    ] == [
        (1, 3, "all_gather"),
        (1, 3, "all_reduce"),
        (1, 3, "reduce_scatter"),
        (2, 50, "all_reduce"),
    ]


def test_no_graphs_after_the_first_step_stops_watching(graphs):
    events = []
    collector = _collector(events)
    engine = SimpleNamespace(num_accumulation_steps=1)
    collector.before_forward_backward(engine, 1)
    collector.after_forward_backward(engine)
    for step in range(2, 5):
        collector.before_forward_backward(engine, step)
        collector.after_forward_backward(engine)
    assert graphs.dp.registrations == 1
    assert not _schedules(events)


def test_per_group_graphs_replay_once_per_accumulation_group(graphs):
    events = []
    collector = _collector(events)
    engine = SimpleNamespace(
        num_accumulation_steps=4, _cuda_graph_per_accumulation_group_enabled=True
    )
    wrapper = SimpleNamespace(_graph=None, _warmup_remaining=0)
    collector.before_forward_backward(engine, 1)
    graphs.wrappers.append(wrapper)
    graphs.tp.fire("ALLREDUCE", 4)
    _capture(graphs, wrapper)
    collector.after_forward_backward(engine)
    gather = _schedules(events)[0]
    # Warm-up calls ran eagerly in step 1, so step 2 is the first fully replayed one.
    assert (
        gather["effective_from_step"],
        gather["replays_per_step"],
        gather["count_per_step"],
        gather["bytes_per_step"],
    ) == (2, 4, 12, 1200)


def test_flight_recorder_reports_eager_only_while_graphs_replay(graphs):
    from wandb.sdk.provenance.comm_stats import CollectiveSummary

    events = []
    collector = _collector(events)
    engine = SimpleNamespace(num_accumulation_steps=1)
    wrapper = SimpleNamespace(_graph=None, _warmup_remaining=0)
    graphs.wrappers.append(wrapper)
    summary = CollectiveSummary("all_reduce", 1, 1, 1.0, 1.0, 1.0, 1.0, 64)
    collector._communication("ok", [summary], 0, _read(1))
    collector.before_forward_backward(engine, 3)
    _capture(graphs, wrapper)
    collector.after_forward_backward(engine)
    collector._communication("ok", [summary], 0, _read(2))
    collector._communication("ok", [summary], 0, _read(3, backoff_s=120.0))
    assert [
        (p["status"], p.get("reason"))
        for _, p in events
        if p.get("collector") == "flight_recorder"
    ] == [
        ("available", None),
        ("partial", "cuda_graph_replay"),
        ("partial", "backed_off"),
    ]


def test_a_hook_failure_disables_the_schedule_and_removes_its_hooks(graphs):
    events = []
    graphs.tp.fail = True
    collector = _collector(events)
    engine = SimpleNamespace(num_accumulation_steps=1)
    collector.before_forward_backward(engine, 1)
    collector.after_forward_backward(engine)
    collector.before_forward_backward(engine, 2)
    assert not graphs.dp.hooks
    assert graphs.dp.registrations == 1
    assert (
        "capability",
        {
            "collector": "communication_schedule",
            "status": "self_disabled",
            "reason": "collector_failure",
        },
    ) in events


def test_close_removes_hooks_left_by_an_unfinished_step(graphs):
    collector = _collector([])
    collector.before_forward_backward(SimpleNamespace(), 1)
    assert graphs.dp.hooks
    collector.close()
    assert not graphs.dp.hooks and not graphs.tp.hooks


def test_a_failing_record_never_reaches_the_collective(graphs):
    events = []
    collector = _collector(events)
    engine = SimpleNamespace(num_accumulation_steps=1)
    wrapper = SimpleNamespace(_graph=None, _warmup_remaining=0)
    graphs.wrappers.append(wrapper)
    collector.before_forward_backward(engine, 3)
    graphs.capturing = True
    graphs.dp.fire("ALLGATHER_BASE", "not a size")
    graphs.capturing = False
    wrapper._graph = object()
    collector.after_forward_backward(engine)
    assert not _schedules(events)
    assert not graphs.dp.hooks
    assert events[-1] == (
        "capability",
        {
            "collector": "communication_schedule",
            "status": "self_disabled",
            "reason": "collector_failure",
        },
    )


def test_a_read_held_by_the_ring_reports_its_cost_over_budget():
    from wandb.sdk.provenance.comm_stats import CollectiveSummary

    events = []
    collector = _collector(events)
    summary = CollectiveSummary("all_gather", 1, 1, 1.0, 1.0, 1.0, 1.0, 64)
    collector._communication(
        "ok",
        [summary],
        0,
        _read(1, cpu_ns=600_000_000, backoff_s=80.0, over_budget=True),
    )
    collector._communication(
        "ok", [summary], 0, _read(2, cpu_ns=600_000_000, over_budget=True)
    )
    collector._communication("ok", [summary], 0, _read(3, backoff_s=208.0))
    assert [
        (p["status"], p.get("reason"), p.get("interval_s"), p.get("count"))
        for _, p in events
        if p.get("collector") == "flight_recorder"
    ] == [
        ("partial", "cpu_over_budget", 80.0, 600),
        ("partial", "cpu_over_budget", None, 600),
        ("partial", "backed_off", 208.0, None),
    ]
