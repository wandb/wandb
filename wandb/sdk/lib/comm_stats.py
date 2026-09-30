"""Summarizes NCCL collective timings from PyTorch's flight recorder."""

from __future__ import annotations

import dataclasses
import math
import os
import pickle
import sys
import time
from collections.abc import Callable, Sequence
from typing import Any

_DEFAULT_INTERVAL_SECONDS = 60.0

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


@dataclasses.dataclass(frozen=True)
class CollectiveSummary:
    """Timings of one collective kind over the entries completed since the last report."""

    name: str
    count: int
    p50_ms: float
    p99_ms: float
    max_ms: float
    total_ms: float
    bytes: int | None


class CommStatsReporter:
    """Publishes a summary of NCCL collectives completed since the previous one."""

    def __init__(
        self,
        publish: Callable[[str, list[CollectiveSummary]], None],
        interval: float | None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._publish = publish
        self._interval = (
            interval if interval and interval > 0 else _DEFAULT_INTERVAL_SECONDS
        )
        self._clock = clock
        self._disabled = False
        self._last_check: float | None = None
        self._seen: dict[tuple[Any, bool], int] = {}

    def maybe_report(self) -> None:
        if self._disabled:
            return
        now = self._clock()
        if self._last_check is not None and now - self._last_check < self._interval:
            return
        self._last_check = now

        # Never import torch on the user's behalf.
        torch = sys.modules.get("torch")
        dist = getattr(torch, "distributed", None)
        c10d = getattr(getattr(torch, "_C", None), "_distributed_c10d", None)
        dump_fn = getattr(c10d, "_dump_nccl_trace", None)
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
                self._publish(STATUS_UNAVAILABLE, [])
                return

            try:
                raw = dump_fn(
                    includeCollectives=True,
                    includeStackTraces=False,
                    onlyActive=False,
                )
            except TypeError:
                raw = dump_fn()

            groups: dict[str, list[dict[str, Any]]] = {}
            seen = dict(self._seen)
            for e in pickle.loads(raw).get("entries") or []:
                if e.get("state") != "completed":
                    continue
                # p2p ops advance p2p_seq_id and leave collective_seq_id unchanged.
                is_p2p = bool(e.get("is_p2p"))
                key = (e.get("pg_id"), is_p2p)
                seq = e.get("p2p_seq_id" if is_p2p else "collective_seq_id")
                if seq is None or seq <= self._seen.get(key, -1):
                    continue
                seen[key] = max(seen.get(key, -1), seq)
                name = str(e.get("profiling_name", "")).removeprefix("nccl:")
                groups.setdefault(name, []).append(e)

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
                        p50_ms=_nearest_rank(durations, 50),
                        p99_ms=_nearest_rank(durations, 99),
                        max_ms=durations[-1] if durations else 0.0,
                        total_ms=sum(durations),
                        bytes=nbytes if timed else None,
                    )
                )

            status = STATUS_OK if timed or not groups else STATUS_NO_TIMING
            self._publish(status, collectives)
        except Exception:
            self._disabled = True


def _nearest_rank(sorted_values: Sequence[float], pct: int) -> float:
    if not sorted_values:
        return 0.0
    rank = math.ceil(pct / 100 * len(sorted_values))
    return sorted_values[max(rank, 1) - 1]
