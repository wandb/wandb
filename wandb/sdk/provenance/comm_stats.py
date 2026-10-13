"""Summarizes NCCL collective timings from PyTorch's flight recorder."""

from __future__ import annotations

import dataclasses
import functools
import math
import os
import pickle
import sys
import threading
import time
from collections.abc import Callable, Sequence
from typing import Any

_DEFAULT_INTERVAL_SECONDS = 60.0

# TorchTitan's comm.trace_buf_size default is 20000.
_MAX_BUFFER_SIZE = 20000
_MAX_DUMP_BYTES = 32 << 20
_READ_CPU_NS = 250_000_000
# Ordered so compound names match before "reduce", "gather" and "scatter".
_COLLECTIVE_FAMILIES = (
    ("all_reduce", "all_reduce"),
    ("allreduce", "all_reduce"),
    ("all_gather", "all_gather"),
    ("allgather", "all_gather"),
    ("reduce_scatter", "reduce_scatter"),
    ("reducescatter", "reduce_scatter"),
    ("all_to_all", "all_to_all"),
    ("alltoall", "all_to_all"),
    ("broadcast", "broadcast"),
    ("barrier", "barrier"),
    ("send", "send"),
    ("recv", "recv"),
    ("gather", "gather"),
    ("scatter", "scatter"),
    ("reduce", "reduce"),
)

# Names are c10::toString(ScalarType), which is what the flight recorder stores.
_DTYPE_BYTES = {
    "Float": 4,
    "Float32": 4,
    "Half": 2,
    "BFloat16": 2,
    "Double": 8,
    "Int": 4,
    "Int32": 4,
    "Long": 8,
    "Int64": 8,
    "Short": 2,
    "Byte": 1,
    "Char": 1,
    "Bool": 1,
}

STATUS_OK = "ok"
STATUS_NO_TIMING = "no_timing"
STATUS_UNAVAILABLE = "unavailable"
STATUS_EMPTY = "recorder_empty"
STATUS_UNRECOGNIZED = "no_recognized_collectives"
STATUS_BUFFER_TOO_LARGE = "buffer_too_large"
STATUS_CPU_BUDGET = "cpu_budget"


@dataclasses.dataclass(frozen=True)
class CollectiveSummary:
    """New collective timings; durations are None for untimed entries."""

    name: str
    count: int
    n_timed: int
    p50_ms: float | None
    p99_ms: float | None
    max_ms: float | None
    total_ms: float | None
    bytes: int | None


class CommStatsReporter:
    """Reads the process-global recorder from a daemon thread."""

    def __init__(
        self,
        publish: Callable[[str, list[CollectiveSummary], int], None],
        interval: float | None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._publish = publish
        self._interval = max(interval or 0, _DEFAULT_INTERVAL_SECONDS)
        self._clock = clock
        self._disabled = False
        self._last_read: float | None = None
        self._last_check: float | None = None
        self._seen: dict[tuple[Any, bool], int] = {}
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def _emit(self, status, collectives, lost) -> None:
        try:
            self._publish(status, collectives, lost)
        except Exception:
            self._disabled = True

    def maybe_start(self) -> None:
        """Starts after distributed initialization; otherwise rate-limits unavailable."""
        if self._thread is not None or self._disabled:
            return

        try:
            # Never import torch on the user's behalf.
            dist = getattr(sys.modules.get("torch"), "distributed", None)
            if dist is None or not dist.is_initialized():
                now = self._clock()
                if self._last_check is None or now - self._last_check >= self._interval:
                    self._last_check = now
                    self._emit(STATUS_UNAVAILABLE, [], 0)
                return

            self._thread = threading.Thread(
                target=self._run,
                name="wandb-comm-stats",
                daemon=True,
            )
            self._thread.start()
        except Exception:
            self._disabled = True
            self._emit(STATUS_UNAVAILABLE, [], 0)

    def stop(self) -> None:
        """Stops the reader thread and waits briefly for an in-flight read."""
        self._disabled = True
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._disabled:
            self.report()
            if self._disabled or self._stop.wait(self._interval):
                return

    def report(self) -> None:
        """Reads the flight recorder once and publishes the new collectives."""
        if self._disabled:
            return

        # Never import torch on the user's behalf.
        torch = sys.modules.get("torch")
        dist = getattr(torch, "distributed", None)
        c10d = getattr(getattr(torch, "_C", None), "_distributed_c10d", None)
        # NCCL records into the CUDA recorder that only _dump_nccl_trace reads.
        dump_fn = getattr(c10d, "_dump_nccl_trace", None)
        fr_dump = getattr(c10d, "_dump_fr_trace", None)
        if dump_fn is None and "backend" in (getattr(fr_dump, "__doc__", None) or ""):
            dump_fn = functools.partial(fr_dump, backend="nccl")
        buffer_size = os.environ.get("TORCH_FR_BUFFER_SIZE") or os.environ.get(
            "TORCH_NCCL_TRACE_BUFFER_SIZE", "0"
        )

        try:
            if (
                dump_fn is None
                or dist is None
                or not dist.is_initialized()
                or int(buffer_size) <= 0
            ):
                self._emit(STATUS_UNAVAILABLE, [], 0)
                return

            if int(buffer_size) > _MAX_BUFFER_SIZE:
                self._disabled = True
                self._emit(STATUS_BUFFER_TOO_LARGE, [], int(buffer_size))
                return
            now = self._clock()
            if self._last_read is not None and now - self._last_read < 60:
                return
            self._last_read = now
            started = time.thread_time_ns()
            raw = dump_fn(
                includeCollectives=True,
                includeStackTraces=False,
                onlyActive=False,
            )
            if len(raw) > _MAX_DUMP_BYTES:
                self._disabled = True
                self._emit(STATUS_UNAVAILABLE, [], 0)
                return

            groups: dict[str, list[dict[str, Any]]] = {}
            seen = dict(self._seen)
            oldest: dict[tuple[Any, bool], int] = {}
            entries = pickle.loads(raw).get("entries") or []
            if not entries:
                self._emit(STATUS_EMPTY, [], 0)
                return
            if len(entries) > _MAX_BUFFER_SIZE:
                self._emit(STATUS_UNAVAILABLE, [], 0)
                self._disabled = True
                return
            for e in entries:
                # p2p ops advance p2p_seq_id and leave collective_seq_id unchanged.
                is_p2p = bool(e.get("is_p2p"))
                key = (e.get("pg_id"), is_p2p)
                seq = e.get("p2p_seq_id" if is_p2p else "collective_seq_id")
                if seq is None:
                    continue
                oldest[key] = min(oldest.get(key, seq), seq)
                if e.get("state") != "completed" or seq <= self._seen.get(key, -1):
                    continue
                seen[key] = max(seen.get(key, -1), seq)
                if len(seen) > 1024:
                    self._disabled = True
                    self._emit(STATUS_UNAVAILABLE, [], 0)
                    return
                name = str(e.get("profiling_name", "")).lower()
                # Unknown names are counted as "other" and never stored.
                family = next(
                    (f for needle, f in _COLLECTIVE_FAMILIES if needle in name),
                    "other",
                )
                groups.setdefault(family, []).append(e)

            # A sequence gap before the oldest entry indicates ring wrap.
            n_lost = sum(
                max(0, first - self._seen[key] - 1)
                for key, first in oldest.items()
                if key in self._seen
            )
            self._seen = seen

            timed = any(
                e.get("duration_ms") is not None for g in groups.values() for e in g
            )
            collectives = []
            for name in sorted(groups):
                group = groups[name]
                durations = sorted(
                    float(e["duration_ms"])
                    for e in group
                    if e.get("duration_ms") is not None
                )
                nbytes: int | None = 0
                for e in group:
                    sizes = e.get("input_sizes") or []
                    dtypes = e.get("input_dtypes") or []
                    widths = [_DTYPE_BYTES.get(d) for d in dtypes]
                    if len(sizes) != len(dtypes) or None in widths:
                        nbytes = None
                        break
                    nbytes += sum(
                        math.prod(s) * w for s, w in zip(sizes, widths, strict=True)
                    )
                collectives.append(
                    CollectiveSummary(
                        name=name,
                        count=len(group),
                        n_timed=len(durations),
                        p50_ms=_nearest_rank(durations, 50) if durations else None,
                        p99_ms=_nearest_rank(durations, 99) if durations else None,
                        max_ms=durations[-1] if durations else None,
                        total_ms=sum(durations) if durations else None,
                        bytes=nbytes if timed else None,
                    )
                )

            status = (
                STATUS_UNRECOGNIZED
                if set(groups) == {"other"}
                else STATUS_OK
                if timed or not groups
                else STATUS_NO_TIMING
            )
            self._emit(status, collectives, n_lost)
            elapsed_ms = (time.thread_time_ns() - started) // 1_000_000
            if elapsed_ms > _READ_CPU_NS // 1_000_000:
                self._disabled = True
                self._emit(STATUS_CPU_BUDGET, [], elapsed_ms)
        except Exception:
            self._disabled = True
            self._emit(STATUS_UNAVAILABLE, [], 0)


def _nearest_rank(sorted_values: Sequence[float], pct: int) -> float:
    rank = math.ceil(pct / 100 * len(sorted_values))
    return sorted_values[max(rank, 1) - 1]
