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


def test_gradient_scan_syncs_once_and_respects_element_budget(monkeypatch):
    import math
    from types import SimpleNamespace

    import torch
    from wandb.sdk.provenance import level1

    events = []
    monkeypatch.setattr(level1, "_SCAN_ELEMENTS", 6)
    monkeypatch.setattr(torch.cuda, "is_initialized", lambda: True)
    monkeypatch.setattr(torch.cuda, "Event", lambda **kwargs: SimpleNamespace())
    monkeypatch.setattr(
        torch.Tensor, "item", lambda self: pytest.fail("per-chunk host sync")
    )
    parameters = [torch.zeros(4, requires_grad=True) for _ in range(2)]
    parameters[0].grad = torch.tensor([3.0, 4.0, math.nan, 1.0])
    parameters[1].grad = torch.ones(4)
    collector = level1.Level1Collectors(
        SimpleNamespace(
            emit=lambda kind, payload: events.append((kind, payload)), dropped=0
        )
    )
    collector._comm = SimpleNamespace(maybe_start=lambda: None, stop=lambda: None)
    engine = SimpleNamespace(
        model_parts=[SimpleNamespace(parameters=lambda: parameters)], device="cpu"
    )
    collector.step(engine, 100)
    diagnostic = next(
        p for kind, p in events if p.get("collector") == "gradient_health"
    )
    assert diagnostic["finite_count"] == 5
    assert diagnostic["nonfinite_count"] == 1
    assert diagnostic["norm"] == pytest.approx(math.sqrt(9 + 16 + 1 + 1 + 1))
    assert (diagnostic["status"], diagnostic["reason"]) == ("partial", "element_budget")
