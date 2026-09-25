from __future__ import annotations

import sys
import types

import pytest
from wandb.sdk.lib.device_binding import DeviceBindingReporter


class _Props:
    def __init__(self, uuid, domain=0, bus=0x1B, device=0):
        self.uuid = uuid
        self.pci_domain_id = domain
        self.pci_bus_id = bus
        self.pci_device_id = device


def _fake_torch(*, initialized=True, device=1, uuid="aaaa-bbbb", props=None):
    cuda = types.SimpleNamespace(
        is_initialized=lambda: initialized,
        current_device=lambda: device,
        get_device_properties=lambda i: props or _Props(uuid),
    )
    return types.SimpleNamespace(cuda=cuda)


class _Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def published():
    return []


@pytest.fixture
def reporter(published):
    clock = _Clock()
    r = DeviceBindingReporter(lambda *a: published.append(a), clock=clock)
    r.clock = clock
    return r


def test_no_torch_publishes_nothing(monkeypatch, reporter, published):
    monkeypatch.delitem(sys.modules, "torch", raising=False)
    reporter.maybe_report()
    assert published == []
    assert "torch" not in sys.modules


def test_cuda_not_initialized_publishes_nothing(monkeypatch, reporter, published):
    monkeypatch.setitem(sys.modules, "torch", _fake_torch(initialized=False))
    reporter.maybe_report()
    assert published == []


def test_publishes_prefixed_uuid_and_pci(monkeypatch, reporter, published):
    monkeypatch.setitem(sys.modules, "torch", _fake_torch(uuid="aaaa-bbbb"))
    reporter.maybe_report()
    assert published == [("GPU-aaaa-bbbb", "00000000:1B:00.0", 1)]


def test_keeps_existing_gpu_prefix(monkeypatch, reporter, published):
    monkeypatch.setitem(sys.modules, "torch", _fake_torch(uuid="GPU-aaaa"))
    reporter.maybe_report()
    assert published[0][0] == "GPU-aaaa"


def test_missing_pci_fields_yield_empty(monkeypatch, reporter, published):
    props = types.SimpleNamespace(uuid="aaaa")
    monkeypatch.setitem(sys.modules, "torch", _fake_torch(props=props))
    reporter.maybe_report()
    assert published == [("GPU-aaaa", "", 1)]


def test_rechecks_after_60s_and_republishes_only_on_change(
    monkeypatch, reporter, published
):
    monkeypatch.setitem(sys.modules, "torch", _fake_torch(uuid="aaaa"))
    reporter.maybe_report()
    reporter.clock.t += 30
    reporter.maybe_report()
    reporter.clock.t += 31
    reporter.maybe_report()
    assert len(published) == 1

    monkeypatch.setitem(sys.modules, "torch", _fake_torch(uuid="cccc"))
    reporter.clock.t += 61
    reporter.maybe_report()
    assert [p[0] for p in published] == ["GPU-aaaa", "GPU-cccc"]


def test_exception_disables(monkeypatch, reporter, published):
    def boom():
        raise RuntimeError("no device")

    torch = _fake_torch()
    torch.cuda.current_device = boom
    monkeypatch.setitem(sys.modules, "torch", torch)
    reporter.maybe_report()
    monkeypatch.setitem(sys.modules, "torch", _fake_torch())
    reporter.maybe_report()
    assert published == []
