from __future__ import annotations

import sys
import types
import unittest.mock


def _fake_torch():
    props = types.SimpleNamespace(uuid="aaaa")
    cuda = unittest.mock.MagicMock()
    cuda.is_initialized.return_value = True
    cuda.current_device.return_value = 0
    cuda.get_device_properties.return_value = props
    return types.SimpleNamespace(cuda=cuda)


def test_setting_off_never_touches_torch(monkeypatch, mock_run):
    torch = _fake_torch()
    monkeypatch.setitem(sys.modules, "torch", torch)
    run = mock_run(use_magic_mock=True)

    run.log({"a": 1})

    torch.cuda.is_initialized.assert_not_called()
    run._interface.publish_device_binding.assert_not_called()


def test_setting_on_publishes_from_log(monkeypatch, mock_run):
    monkeypatch.setitem(sys.modules, "torch", _fake_torch())
    run = mock_run(use_magic_mock=True, settings={"x_provenance_logs": True})

    run.log({"a": 1})

    run._interface.publish_device_binding.assert_called_once_with(
        uuid="GPU-aaaa",
        pci_bus_id="",
        cuda_index=0,
        source="cuda_runtime",
    )


def _fake_dist_torch():
    torch = _fake_torch()
    torch.distributed = unittest.mock.MagicMock()
    torch.distributed.is_initialized.return_value = True
    return torch


def test_comm_setting_off_never_touches_torch(monkeypatch, mock_run):
    torch = _fake_dist_torch()
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setenv("TORCH_NCCL_TRACE_BUFFER_SIZE", "2000")
    run = mock_run(use_magic_mock=True, settings={"x_provenance_logs": True})

    run.log({"a": 1})

    torch.distributed.is_initialized.assert_not_called()
    run._interface.publish_comm_stats.assert_not_called()


def test_comm_needs_provenance_logs(monkeypatch, mock_run):
    torch = _fake_dist_torch()
    monkeypatch.setitem(sys.modules, "torch", torch)
    run = mock_run(use_magic_mock=True, settings={"x_provenance_comm": True})

    run.log({"a": 1})

    torch.distributed.is_initialized.assert_not_called()
    run._interface.publish_comm_stats.assert_not_called()


def test_comm_setting_on_publishes_from_log(monkeypatch, mock_run):
    torch = _fake_dist_torch()
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.delenv("TORCH_NCCL_TRACE_BUFFER_SIZE", raising=False)
    monkeypatch.delenv("TORCH_FR_BUFFER_SIZE", raising=False)
    run = mock_run(
        use_magic_mock=True,
        settings={"x_provenance_logs": True, "x_provenance_comm": True},
    )

    run.log({"a": 1})
    run.log({"a": 2})

    run._interface.publish_comm_stats.assert_called_once_with(
        status="unavailable", collectives=[]
    )
