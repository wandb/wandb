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
