import os

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


def _collector(events, dropped=0):
    from types import SimpleNamespace

    from wandb.sdk.provenance import level1

    collector = level1.Level1Collectors(
        SimpleNamespace(
            emit=lambda kind, payload: events.append((kind, payload)), dropped=dropped
        )
    )
    collector._comm = SimpleNamespace(maybe_start=lambda: None, stop=lambda: None)
    collector._transport_started = True
    return collector


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


def test_flight_recorder_reports_available_after_unavailable(monkeypatch):
    import sys
    from types import SimpleNamespace

    c10d = SimpleNamespace(_dump_nccl_trace=lambda **kwargs: b"")
    torch = SimpleNamespace(_C=SimpleNamespace(_distributed_c10d=c10d))
    monkeypatch.setitem(sys.modules, "torch", torch)
    events = []
    collector = _collector(events)
    from wandb.sdk.provenance.comm_stats import CollectiveSummary

    def summary(name):
        return CollectiveSummary(name, 3, 3, 1.0, 1.0, 1.0, 3.0, 64)

    collector._communication("unavailable", [], 0)
    collector._communication("recorder_empty", [], 0)
    collector._communication("no_recognized_collectives", [summary("other")], 0)
    collector._communication("ok", [], 0)
    collector._communication("ok", [summary("all_gather")], 0)
    collector._communication("ok", [summary("all_gather")], 0)
    collector._communication("no_timing", [summary("all_gather")], 0)
    assert [
        (p["status"], p.get("reason"), p.get("count"))
        for kind, p in events
        if p.get("collector") == "flight_recorder"
    ] == [
        ("unavailable", "recorder_unavailable", None),
        ("partial", "recorder_empty", None),
        ("partial", "no_recognized_collectives", 3),
        ("available", None, None),
        ("partial", "no_timing", None),
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


def test_flight_recorder_without_the_nccl_dump_is_partial(monkeypatch):
    import sys
    from types import SimpleNamespace

    torch = SimpleNamespace(_C=SimpleNamespace(_distributed_c10d=SimpleNamespace()))
    monkeypatch.setitem(sys.modules, "torch", torch)
    events = []
    from wandb.sdk.provenance.comm_stats import CollectiveSummary

    summary = CollectiveSummary("all_gather", 1, 1, 1.0, 1.0, 1.0, 1.0, 64)
    _collector(events)._communication("ok", [summary], 0)
    assert events[-2][1] == {
        "collector": "flight_recorder",
        "status": "partial",
        "reason": "generic_recorder",
    }


def test_flight_recorder_bound_reasons_carry_the_size():
    events = []
    collector = _collector(events)
    collector._communication("buffer_too_large", [], 50000)
    collector._communication("cpu_budget", [], 300)
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
