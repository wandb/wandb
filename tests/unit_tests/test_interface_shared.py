from __future__ import annotations

import unittest.mock

from wandb.sdk.interface.interface_queue import InterfaceQueue


def test_publish_device_binding_marks_record_local():
    iface = InterfaceQueue()
    iface._publish = unittest.mock.MagicMock()

    iface.publish_device_binding(
        uuid="GPU-aaaa", pci_bus_id="", cuda_index=0, source="cuda_runtime"
    )

    rec = iface._publish.call_args.args[0]
    assert rec.control.local is True
