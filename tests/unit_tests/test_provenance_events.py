import json
import threading
from queue import Queue

import pytest


@pytest.mark.parametrize("key", [None, "", "ab" * 31, "AB" * 32, "not-hex", "ab" * 32])
def test_binding_identity_is_redacted_before_protobuf_serialization(monkeypatch, key):
    from wandb.sdk.interface.interface_queue import InterfaceQueue
    from wandb.sdk.provenance.events import EventEmitter

    if key is None:
        monkeypatch.delenv("WANDB_X_PROVENANCE_REDACTION_KEY", raising=False)
    else:
        monkeypatch.setenv("WANDB_X_PROVENANCE_REDACTION_KEY", key)
    records = Queue()
    emitter = EventEmitter(InterfaceQueue(record_q=records), "writer")
    payload = {"gpu_uuid": "GPU-private", "hostname": "private-host", "cuda_index": 0}
    emitter.emit("binding", payload)
    emitter.close()
    binding = records.get_nowait()
    assert binding.provenance.kind == "binding"
    decoded = json.loads(binding.provenance.payload_json)
    for raw in ("GPU-private", "private-host"):
        assert raw.encode() not in binding.SerializeToString()
        assert raw not in str(binding)
    assert "gpu_uuid" not in decoded
    assert "hostname" not in decoded
    if key == "ab" * 32:
        assert decoded["gpu_uuid_hmac"] == "gpu_uuid_b9ace856f2313cfd555be18d"
        assert decoded["hostname_hmac"] == "hostname_1178efd7a071493cc4c19ed4"
        assert key.encode() not in binding.SerializeToString()
    else:
        assert "gpu_uuid_hmac" not in decoded
        assert "hostname_hmac" not in decoded
        assert decoded["status"] == "partial"
        assert decoded["reason"] in ("missing_redaction_key", "invalid_redaction_key")
    assert payload["gpu_uuid"] == "GPU-private"


def test_missing_key_keeps_non_binding_status(monkeypatch):
    from wandb.sdk.interface.interface_queue import InterfaceQueue
    from wandb.sdk.provenance.events import EventEmitter

    monkeypatch.delenv("WANDB_X_PROVENANCE_REDACTION_KEY", raising=False)
    records = Queue()
    emitter = EventEmitter(InterfaceQueue(record_q=records), "writer")
    emitter.emit(
        "capability",
        {"collector": "platform", "status": "available", "hostname": "private"},
    )
    emitter.close()
    decoded = json.loads(records.get_nowait().provenance.payload_json)
    assert decoded == {"collector": "platform", "status": "available"}


def test_malformed_pseudonym_never_enters_protobuf(monkeypatch):
    from wandb.sdk.interface.interface_queue import InterfaceQueue
    from wandb.sdk.provenance.events import EventEmitter

    monkeypatch.setenv("WANDB_X_PROVENANCE_REDACTION_KEY", "ab" * 32)
    records = Queue()
    emitter = EventEmitter(InterfaceQueue(record_q=records), "writer")
    emitter.emit("binding", {"gpu_uuid_hmac": "GPU-private"})
    emitter.close()
    assert emitter.dropped == 1
    while not records.empty():
        record = records.get_nowait()
        assert b"GPU-private" not in record.SerializeToString()


def test_event_queue_is_byte_bounded_and_reports_drops():
    from wandb.sdk.provenance.events import EventEmitter

    entered, release = threading.Event(), threading.Event()
    records = []

    class Interface:
        def publish_provenance_record(self, record):
            entered.set()
            release.wait(5)
            records.append(record)

    emitter = EventEmitter(Interface(), "writer")
    try:
        emitter.emit("step", {"step": 0})
        assert entered.wait(1)
        for _ in range(200):
            emitter.emit("test_ground_truth", {"scenario": "x" * 60000})
        assert emitter._queued_bytes <= 4 << 20
        assert emitter.dropped > 100
    finally:
        release.set()
        emitter.close()
    assert not emitter._thread.is_alive()


def test_binding_is_recorded_only_when_it_changes(monkeypatch):
    from wandb.sdk.interface.interface_queue import InterfaceQueue
    from wandb.sdk.provenance.events import EventEmitter

    monkeypatch.setenv("WANDB_X_PROVENANCE_REDACTION_KEY", "ab" * 32)
    records = Queue()
    emitter = EventEmitter(InterfaceQueue(record_q=records), "writer")
    for index in (0, 0, 0, 1, 1, 0):
        emitter.emit("binding", {"gpu_uuid": f"GPU-{index}", "cuda_index": index})
    emitter.close()
    kinds = []
    while not records.empty():
        record = records.get_nowait().provenance
        if record.kind == "binding":
            kinds.append(json.loads(record.payload_json)["cuda_index"])
    assert kinds == [0, 1, 0]
