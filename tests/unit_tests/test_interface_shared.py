from __future__ import annotations

import unittest.mock

from wandb.sdk.interface.interface_queue import InterfaceQueue
from wandb.sdk.lib.comm_stats import CollectiveSummary


def test_publish_device_binding_marks_record_local():
    iface = InterfaceQueue()
    iface._publish = unittest.mock.MagicMock()

    iface.publish_device_binding(
        uuid="GPU-aaaa", pci_bus_id="", cuda_index=0, source="cuda_runtime"
    )

    rec = iface._publish.call_args.args[0]
    assert rec.control.local is True


def test_publish_comm_stats_marks_record_local():
    iface = InterfaceQueue()
    iface._publish = unittest.mock.MagicMock()

    iface.publish_comm_stats(
        status="ok",
        collectives=[
            CollectiveSummary("all_reduce", 3, 1.0, 2.0, 2.5, 4.5, 96),
            CollectiveSummary("broadcast", 1, 1.0, 1.0, 1.0, 1.0, None),
        ],
    )

    rec = iface._publish.call_args.args[0]
    assert rec.control.local is True
    assert rec.comm_stats.status == "ok"
    reduce, bcast = rec.comm_stats.collectives
    assert (reduce.name, reduce.count, reduce.p99_ms, reduce.bytes) == (
        "all_reduce",
        3,
        2.0,
        96,
    )
    assert reduce.HasField("bytes")
    assert not bcast.HasField("bytes")
