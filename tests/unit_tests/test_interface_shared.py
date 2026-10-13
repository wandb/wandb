from __future__ import annotations

import unittest.mock

from wandb.sdk.interface.interface_queue import InterfaceQueue


def test_provenance_start_request_is_local_req_resp():
    from wandb.proto import wandb_internal_pb2 as pb

    iface = InterfaceQueue()
    iface._deliver = unittest.mock.MagicMock()
    iface.deliver_provenance_start(
        pb.ProvenanceStartRequest(protocol_version=2, run_id="job-1", rank=1)
    )
    record = iface._deliver.call_args.args[0]
    assert record.control.local
    assert record.control.req_resp
    assert record.request.provenance_start.protocol_version == 2
    assert record.request.provenance_start.rank == 1


def test_provenance_record_is_local():
    from queue import Queue

    records = Queue()
    iface = InterfaceQueue(record_q=records)
    from wandb.proto import wandb_internal_pb2 as pb

    iface.publish_provenance_record(
        pb.ProvenanceRecord(
            kind="step", payload_json=b'{"step":3}', monotonic_ns=7, wall_time_ns=11
        )
    )
    record = records.get_nowait()
    assert record.control.local
    assert record.provenance.kind == "step"
    assert record.provenance.payload_json == b'{"step":3}'
    assert record.provenance.monotonic_ns == 7
