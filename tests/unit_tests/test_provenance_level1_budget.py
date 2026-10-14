import contextlib
import sys
from types import SimpleNamespace


def test_gemm_is_lazy_bounded_and_at_most_every_hundred_steps(monkeypatch):
    from wandb.sdk.provenance.level1 import Level1Collectors

    allocations, multiplies, events = [], [], []

    class Event:
        def record(self):
            pass

        def query(self):
            return True

        def elapsed_time(self, other):
            return 1.0

    def full(shape, value, **kwargs):
        allocations.append(shape)
        return object()

    def forbidden(*args, **kwargs):
        raise AssertionError("RNG must not be consumed")

    torch = SimpleNamespace(
        no_grad=contextlib.nullcontext,
        full=full,
        mm=lambda *args, **kwargs: multiplies.append(True),
        float16="float16",
        cuda=SimpleNamespace(
            is_initialized=lambda: True, Event=lambda **kwargs: Event()
        ),
        rand=forbidden,
        randn=forbidden,
    )
    monkeypatch.setitem(sys.modules, "torch", torch)
    accounted = []
    collector = Level1Collectors(
        SimpleNamespace(
            emit=lambda kind, payload: events.append((kind, payload)),
            dropped=0,
            account=lambda **kw: accounted.append(kw),
        )
    )
    collector._comm = SimpleNamespace(maybe_start=lambda: None, stop=lambda: None)
    assert allocations == []
    engine = SimpleNamespace(model_parts=[], device="cuda:0")
    for step in range(1, 202):
        collector.step(engine, step)
    assert len(allocations) == 3
    assert sum(rows * columns * 2 for rows, columns in allocations) <= 64 << 20
    # One untimed warm-up, then one timed probe per 100 steps.
    assert len(multiplies) == 4
    # The probe tensors stay owned by the collector, and each sampled step is charged.
    assert [a["held_bytes"] for a in accounted if "held_bytes" in a] == [
        3 * 2048**2 * 2
    ]
    assert [a["cpu_ns"] >= 0 for a in accounted if "cpu_ns" in a] == [True] * 3
    collector.close()
    assert collector._tensors is None


def test_queue_pressure_disables_active_diagnostics_before_allocation(monkeypatch):
    from wandb.sdk.provenance.level1 import Level1Collectors

    events = []
    collector = Level1Collectors(
        SimpleNamespace(
            emit=lambda kind, payload: events.append((kind, payload)), dropped=1
        )
    )
    collector._comm = SimpleNamespace(maybe_start=lambda: None, stop=lambda: None)
    collector.step(SimpleNamespace(), 1)
    assert collector._disabled
    assert collector._tensors is None
    assert events[-1][1]["reason"] == "queue_pressure"


def test_gated_off_collectors_report_why_they_did_not_run(monkeypatch):
    from wandb.sdk.provenance.level1 import Level1Collectors

    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(cuda=SimpleNamespace(is_initialized=lambda: False)),
    )

    def skipped(step_count):
        events = []
        collector = Level1Collectors(
            SimpleNamespace(
                emit=lambda kind, payload: events.append((kind, payload)), dropped=0
            )
        )
        collector._comm = SimpleNamespace(maybe_start=lambda: None, stop=lambda: None)
        for step in range(1, step_count + 1):
            collector.step(SimpleNamespace(), step)
        collector.close()
        return [
            (payload["collector"], payload["status"], payload["reason"])
            for kind, payload in events
            if kind == "capability"
            and payload["collector"] in ("gradient_health", "active_diagnostics")
        ]

    assert skipped(150) == [
        ("gradient_health", "unavailable", "cuda_unavailable"),
        ("active_diagnostics", "unavailable", "cuda_unavailable"),
    ]
    assert skipped(0) == [
        ("gradient_health", "unavailable", "step_threshold_not_reached"),
        ("active_diagnostics", "unavailable", "step_threshold_not_reached"),
    ]
