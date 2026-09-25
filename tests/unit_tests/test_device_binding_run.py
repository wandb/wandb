from __future__ import annotations

import sys
import threading
import time
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
    run = mock_run(use_magic_mock=True, settings={"x_provenance": True})

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
    run = mock_run(use_magic_mock=True, settings={"x_provenance": True})

    run.log({"a": 1})

    torch.distributed.is_initialized.assert_not_called()
    run._interface.publish_comm_stats.assert_not_called()


def test_comm_needs_provenance(monkeypatch, mock_run):
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
        settings={"x_provenance": True, "x_provenance_comm": True},
    )

    try:
        run.log({"a": 1})
        run.log({"a": 2})
        thread = run._comm_stats_reporter._thread
        assert thread is not None and thread is not threading.current_thread()
        deadline = time.monotonic() + 5
        while not run._interface.publish_comm_stats.called:
            assert time.monotonic() < deadline
            time.sleep(0.005)
    finally:
        run._comm_stats_reporter.stop()

    run._interface.publish_comm_stats.assert_called_once_with(
        status="unavailable", collectives=[], n_lost=0
    )


def test_finish_stops_comm_reader(monkeypatch, mock_run):
    monkeypatch.setitem(sys.modules, "torch", _fake_dist_torch())
    run = mock_run(
        use_magic_mock=True,
        settings={"x_provenance": True, "x_provenance_comm": True},
    )
    run.log({"a": 1})
    thread = run._comm_stats_reporter._thread
    run._wl = unittest.mock.MagicMock(assert_service=unittest.mock.MagicMock())

    run.finish()

    assert not thread.is_alive()
