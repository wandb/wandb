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
            CollectiveSummary("all_reduce", 3, 3, 1.0, 2.0, 2.5, 4.5, 96),
            CollectiveSummary("broadcast", 1, 1, 1.0, 1.0, 1.0, 1.0, None),
        ],
        n_lost=7,
    )

    rec = iface._publish.call_args.args[0]
    assert rec.control.local is True
    assert rec.comm_stats.status == "ok"
    assert rec.comm_stats.n_lost == 7
    reduce, bcast = rec.comm_stats.collectives
    assert (reduce.name, reduce.count, reduce.p99_ms, reduce.bytes) == (
        "all_reduce",
        3,
        2.0,
        96,
    )
    assert reduce.HasField("bytes")
    assert not bcast.HasField("bytes")


def test_publish_comm_stats_leaves_untimed_durations_unset():
    iface = InterfaceQueue()
    iface._publish = unittest.mock.MagicMock()

    iface.publish_comm_stats(
        status="ok",
        collectives=[
            CollectiveSummary("all_reduce", 2, 2, 1.0, 2.0, 2.0, 3.0, 8),
            CollectiveSummary("send", 1, 0, None, None, None, None, 4),
        ],
        n_lost=0,
    )

    reduce, send = iface._publish.call_args.args[0].comm_stats.collectives
    assert (reduce.n_timed, reduce.HasField("p50_ms"), reduce.total_ms) == (
        2,
        True,
        3.0,
    )
    assert send.n_timed == 0
    for field in ("p50_ms", "p99_ms", "max_ms", "total_ms"):
        assert not send.HasField(field)
