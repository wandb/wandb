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

# Torch's own precedence and default for the recorder size.
_BUFFER_ENV = ("TORCH_FR_BUFFER_SIZE", "TORCH_NCCL_TRACE_BUFFER_SIZE")
_DEFAULT_BUFFER_SIZE = 2000
# TorchTitan's comm.trace_buf_size default is 20000.
_MAX_BUFFER_SIZE = 20000
_MAX_DUMP_BYTES = 32 << 20
# CPU allowed per nominal interval; a costlier read stretches the next one.
_READ_CPU_NS = 250_000_000
_BACKOFF = (1, 2, 4)
_MAX_TRACKED = 1024
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
STATUS_DETACHED = "recorder_detached"
STATUS_PENDING = "no_completed_collectives"
STATUS_UNRECOGNIZED = "no_recognized_collectives"
STATUS_BUFFER_TOO_LARGE = "buffer_too_large"
STATUS_CPU_BUDGET = "cpu_budget"


@functools.lru_cache(maxsize=256)
def collective_family(name: Any) -> str:
    """Returns the collective family of an op name; unknown names are "other"."""
    lowered = str(name).lower()
    return next((f for needle, f in _COLLECTIVE_FAMILIES if needle in lowered), "other")


def fr_buffer_setting() -> tuple[str | None, int]:
    """Returns the variable torch sizes the recorder from (None if unset) and the size."""
    for name in _BUFFER_ENV:
        if value := os.environ.get(name):
            try:
                return name, int(value)
            except ValueError:
                return name, 0
    return None, _DEFAULT_BUFFER_SIZE


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


@dataclasses.dataclass(frozen=True)
class RecorderRead:
    """One recorder dump; every record a read produces shares these values."""

    read_id: int
    # Wall-clock ns of the previous read, None for the first.
    start_ns: int | None
    end_ns: int
    cpu_ns: int
    dump_bytes: int
    # Seconds until the next read when it is later than the nominal interval.
    backoff_s: float | None = None


class CommStatsReporter:
    """Reads the process-global recorder from a daemon thread."""

    def __init__(
        self,
        publish: Callable[
            [str, list[CollectiveSummary], int, RecorderRead | None], None
        ],
        interval: float | None,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], int] = time.time_ns,
    ) -> None:
        self._publish = publish
        self._interval = max(interval or 0, _DEFAULT_INTERVAL_SECONDS)
        self._clock = clock
        self._wall_clock = wall_clock
        self._disabled = False
        self._last_read: float | None = None
        self._wait = self._interval
        self._last_check: float | None = None
        self._reads = 0
        self._last_end_ns: int | None = None
        # Per (pg, p2p): highest completed seq and the lower seqs still pending.
        self._seen: dict[tuple[Any, bool], tuple[int, frozenset[int]]] = {}
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def _emit(self, status, collectives, lost, read=None) -> None:
        try:
            self._publish(status, collectives, lost, read)
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
            if self._disabled or self._stop.wait(self._wait):
                return

    def report(self) -> None:  # noqa: C901
        """Reads the flight recorder once and publishes the new collectives."""
        if self._disabled:
            return

        # Never import torch on the user's behalf.
        torch = sys.modules.get("torch")
        dist = getattr(torch, "distributed", None)
        c10d = getattr(getattr(torch, "_C", None), "_distributed_c10d", None)
        _, buffer_size = fr_buffer_setting()

        try:
            if dist is None or not dist.is_initialized() or buffer_size <= 0:
                self._emit(STATUS_UNAVAILABLE, [], 0)
                return

            if buffer_size > _MAX_BUFFER_SIZE:
                self._disabled = True
                self._emit(STATUS_BUFFER_TOO_LARGE, [], buffer_size)
                return
            now = self._clock()
            if self._last_read is not None and now - self._last_read < self._wait:
                return
            self._last_read = now

            pg = dist.distributed_c10d._get_default_group()
            devices = list(pg._device_types)
            device = next((d for d in devices if d.type == "cuda"), devices[0])
            backend = pg._get_backend(device).name()
            fr_dump = getattr(c10d, "_dump_fr_trace", None)
            # Stock ProcessGroupNCCL feeds the CUDA-event recorder; others feed their own.
            if backend == "nccl" and hasattr(c10d, "_dump_nccl_trace"):
                dump_fn = c10d._dump_nccl_trace
            elif "backend" in (getattr(fr_dump, "__doc__", None) or ""):
                dump_fn = functools.partial(fr_dump, backend=backend.replace(":", "_"))
            else:
                self._emit(STATUS_UNAVAILABLE, [], 0)
                return
            started = time.thread_time_ns()
            end_ns = self._wall_clock()
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
            # Per (pg, p2p): present seqs, completed seqs, prior watermark, prior pending.
            tracks: dict[
                tuple[Any, bool], tuple[set[int], set[int], int, frozenset[int]]
            ] = {}
            dump = pickle.loads(raw)
            entries = dump.get("entries") or []
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
                track = tracks.get(key)
                if track is None:
                    prior = self._seen.get(key, (-1, frozenset()))
                    track = tracks[key] = (set(), set(), *prior)
                seqs, done, watermark, pending = track
                seqs.add(seq)
                # Coalesced ops share a seq, so a seq is counted once.
                if e.get("state") != "completed" or seq in done:
                    continue
                done.add(seq)
                if seq <= watermark and seq not in pending:
                    continue
                # Unknown names are counted as "other" and never stored.
                family = collective_family(e.get("profiling_name", ""))
                groups.setdefault(family, []).append(e)

            seen = dict(self._seen)
            n_lost = 0
            for key, (seqs, done, watermark, pending) in tracks.items():
                if key in self._seen:
                    # A seq gap before the oldest entry indicates ring wrap.
                    n_lost += max(0, min(seqs) - watermark - 1)
                    # Pending seqs that left the ring never showed their completion.
                    n_lost += len(pending - seqs)
                top = max((watermark, *done))
                if top < 0:
                    continue
                waiting = sorted(s for s in seqs - done if s < top)
                n_lost += max(0, len(waiting) - _MAX_TRACKED)
                seen[key] = (top, frozenset(waiting[-_MAX_TRACKED:]))
            if len(seen) > _MAX_TRACKED:
                self._disabled = True
                self._emit(STATUS_UNAVAILABLE, [], 0)
                return
            self._seen = seen

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
                        bytes=nbytes,
                    )
                )

            # Groups register with the recorder they feed; none means nothing does.
            status = (
                (STATUS_EMPTY if dump.get("pg_config") else STATUS_DETACHED)
                if not entries
                else STATUS_PENDING
                if not seen
                else STATUS_UNRECOGNIZED
                if set(groups) == {"other"}
                else STATUS_OK
                if not groups or any(c.n_timed for c in collectives)
                else STATUS_NO_TIMING
            )
            cpu_ns = time.thread_time_ns() - started
            backoff = next((m for m in _BACKOFF if cpu_ns <= _READ_CPU_NS * m), None)
            self._wait = self._interval * (backoff or 1)
            self._reads += 1
            read = RecorderRead(
                self._reads,
                self._last_end_ns,
                end_ns,
                cpu_ns,
                len(raw),
                self._wait if backoff and backoff > 1 else None,
            )
            self._last_end_ns = end_ns
            self._emit(status, collectives, n_lost, read)
            if backoff is None:
                self._disabled = True
                self._emit(STATUS_CPU_BUDGET, [], cpu_ns // 1_000_000)
        except Exception:
            self._disabled = True
            self._emit(STATUS_UNAVAILABLE, [], 0)


def _nearest_rank(sorted_values: Sequence[float], pct: int) -> float:
    rank = math.ceil(pct / 100 * len(sorted_values))
    return sorted_values[max(rank, 1) - 1]
