from __future__ import annotations

import dataclasses
import hmac
import json
import os
import queue
import threading
import time
from collections.abc import Mapping
from typing import Any


@dataclasses.dataclass(frozen=True)
class FrameworkEvent:
    kind: str
    payload: Mapping[str, Any]


class EventEmitter:
    def __init__(self, interface: Any, writer_id: str) -> None:
        self.writer_id = writer_id
        self._interface = interface
        self._pid = os.getpid()
        key_text = os.environ.get("WANDB_X_PROVENANCE_REDACTION_KEY", "")
        self._redaction_key = (
            bytes.fromhex(key_text)
            if len(key_text) == 64
            and all(char in "0123456789abcdef" for char in key_text)
            else b""
        )
        self._identity_reason = (
            "invalid_redaction_key" if key_text else "missing_redaction_key"
        )
        self._queue: queue.Queue[tuple[str, bytes, int, int]] = queue.Queue(1024)
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._queued_bytes = 0
        self._peak_bytes = 0
        self._cpu_ns = 0
        self.dropped = 0
        self.disabled = False
        self._binding: bytes | None = None
        self._thread = threading.Thread(
            target=self._work, name="wandb-provenance", daemon=True
        )
        self._thread.start()

    def emit(self, kind: str, payload: Mapping[str, Any]) -> None:
        if self.disabled or os.getpid() != self._pid or self._stop.is_set():
            return
        started = time.thread_time_ns()
        try:
            payload = dict(payload)
            for name in (
                "gpu_uuid",
                "hostname",
                "instance_id",
                "pod_name",
                "node_name",
                "scheduler_uid",
                "topology_value",
            ):
                raw = payload.pop(name, None)
                field = name + "_hmac"
                if raw is not None and self._redaction_key:
                    if not isinstance(raw, str) or not raw:
                        self.dropped += 1
                        return
                    payload[field] = (
                        name
                        + "_"
                        + hmac.digest(
                            self._redaction_key,
                            (name + "\x00" + raw).encode(),
                            "sha256",
                        )[:12].hex()
                    )
                if raw is None and field not in payload:
                    continue
                if not self._redaction_key:
                    payload.pop(field, None)
                    if kind == "binding":
                        payload["status"] = "partial"
                        payload["reason"] = self._identity_reason
                    continue
                value = payload[field]
                prefix = name + "_"
                if (
                    not isinstance(value, str)
                    or not value.startswith(prefix)
                    or len(value) != len(prefix) + 24
                    or any(
                        char not in "0123456789abcdef" for char in value[len(prefix) :]
                    )
                ):
                    self.dropped += 1
                    return
            encoded = json.dumps(
                payload, allow_nan=False, separators=(",", ":")
            ).encode()
            if len(encoded) > 65536:
                self.dropped += 1
                return
            with self._lock:
                # The manifest carries the current binding, so only changes are recorded.
                if kind == "binding" and encoded == self._binding:
                    return
                if self._queued_bytes + len(encoded) > 4 << 20:
                    self.dropped += 1
                    return
                self._queue.put_nowait(
                    (kind, encoded, time.monotonic_ns(), time.time_ns())
                )
                if kind == "binding":
                    self._binding = encoded
                self._queued_bytes += len(encoded)
                self._peak_bytes = max(
                    self._peak_bytes, self._queued_bytes + self._queue.qsize() * 128
                )
        except Exception:
            self.dropped += 1
        finally:
            with self._lock:
                self._cpu_ns += time.thread_time_ns() - started

    def _work(self) -> None:
        from wandb.proto import wandb_internal_pb2 as pb

        last_quality = time.monotonic()
        while not self._stop.is_set() or not self._queue.empty():
            try:
                record = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            with self._lock:
                self._queued_bytes -= len(record[1])
            started = time.thread_time_ns()
            try:
                if not self.disabled:
                    kind, payload, monotonic_ns, wall_time_ns = record
                    self._interface.publish_provenance_record(
                        pb.ProvenanceRecord(
                            kind=kind,
                            payload_json=payload,
                            monotonic_ns=monotonic_ns,
                            wall_time_ns=wall_time_ns,
                        )
                    )
                else:
                    self.dropped += 1
            except Exception:
                self.disabled = True
            finally:
                self._queue.task_done()
                with self._lock:
                    self._cpu_ns += time.thread_time_ns() - started
            if time.monotonic() - last_quality >= 60:
                self.emit(
                    "quality",
                    {
                        "collector_cpu_ns": self._cpu_ns,
                        "peak_memory_bytes": self._peak_bytes,
                        "dropped_records": self.dropped,
                        "queue_depth": self._queue.qsize(),
                    },
                )
                last_quality = time.monotonic()

    def close(self) -> None:
        self.emit(
            "quality",
            {
                "collector_cpu_ns": self._cpu_ns,
                "peak_memory_bytes": self._peak_bytes,
                "dropped_records": self.dropped,
                "queue_depth": self._queue.qsize(),
            },
        )
        self._stop.set()
        self._thread.join(timeout=1)
        self.dropped += self._queue.qsize()
