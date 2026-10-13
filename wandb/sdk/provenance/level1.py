from __future__ import annotations

import os
import sys
import time
from typing import Any

from .comm_stats import CommStatsReporter
from .timing import CudaEventQueue

_SCAN_ELEMENTS = 64 << 20


def install_level1_bootstrap() -> None:
    if "torch.distributed" in sys.modules:
        return
    if (
        "TORCH_FR_BUFFER_SIZE" not in os.environ
        and "TORCH_NCCL_TRACE_BUFFER_SIZE" not in os.environ
    ):
        os.environ["TORCH_NCCL_TRACE_BUFFER_SIZE"] = "2000"


class Level1Collectors:
    def __init__(self, emit: Any) -> None:
        self.emit = emit
        self._comm = CommStatsReporter(self._communication, 60)
        self._last_step = -100
        self._tensors = None
        self._timing = None
        self._disabled = False
        self._boundary_reported = False
        self._sampled = False
        self._cuda_reported = False
        self.emit.emit(
            "capability",
            {
                "collector": "nccl_transport",
                "status": "unavailable",
                "reason": "bounded_source_unavailable",
            },
        )

    def _communication(self, status, collectives, lost):
        if status == "unavailable":
            self.emit.emit(
                "capability",
                {
                    "collector": "flight_recorder",
                    "status": "unavailable",
                    "reason": "recorder_unavailable",
                },
            )
            return
        for collective in collectives:
            payload = {
                "collective": collective.name,
                "count": collective.count,
                "timed_count": collective.n_timed,
                "lost_count": lost,
            }
            for field in ("p50_ms", "p99_ms", "max_ms", "total_ms", "bytes"):
                value = getattr(collective, field)
                if value is not None:
                    payload[field] = value
            self.emit.emit("communication", payload)

    def step(self, engine, step: int) -> None:
        if self._disabled:
            return
        self._comm.maybe_start()
        if not self._boundary_reported:
            self._boundary_reported = True
            self.emit.emit(
                "capability",
                {
                    "collector": "nccl_sweep",
                    "status": "unsupported",
                    "reason": "unsupported_boundary",
                },
            )
        if self._timing is not None:
            for phase in self._timing.completed():
                if phase.duration_ms > 100:
                    self.emit.emit(
                        "capability",
                        {
                            "collector": "active_diagnostics",
                            "status": "self_disabled",
                            "reason": "gpu_budget",
                        },
                    )
                    self._disabled = True
                    return
                self.emit.emit(
                    "diagnostic",
                    {
                        "phase": phase.phase,
                        "step": phase.step,
                        "duration_ms": phase.duration_ms,
                    },
                )
        if step - self._last_step < 100:
            return
        self._last_step = step
        self._sampled = True
        if getattr(self.emit, "dropped", 0):
            self.emit.emit(
                "capability",
                {
                    "collector": "active_diagnostics",
                    "status": "self_disabled",
                    "reason": "queue_pressure",
                },
            )
            self._disabled = True
            return
        torch = sys.modules.get("torch")
        if torch is None or not torch.cuda.is_initialized():
            if not self._cuda_reported:
                self._cuda_reported = True
                self._report_skipped("cuda_unavailable")
            return
        try:
            with torch.no_grad():
                if not self._scan_gradients(torch, engine, step):
                    return
                if self._tensors is None:
                    self._tensors = tuple(
                        torch.full(
                            (2048, 2048),
                            0.01,
                            device=engine.device,
                            dtype=torch.float16,
                        )
                        for _ in range(3)
                    )
                    self._timing = CudaEventQueue(
                        lambda: torch.cuda.Event(enable_timing=True), capacity=4
                    )
                token = self._timing.start("gemm", step)
                if token is not None:
                    torch.mm(self._tensors[0], self._tensors[1], out=self._tensors[2])
                    self._timing.finish(token)
        except Exception:
            self._disabled = True
            self.emit.emit(
                "capability",
                {
                    "collector": "active_diagnostics",
                    "status": "self_disabled",
                    "reason": "collector_failure",
                },
            )

    def _scan_gradients(self, torch, engine, step: int) -> bool:
        started = time.thread_time_ns()
        scanned = 0
        totals = None
        for part in engine.model_parts:
            for parameter in part.parameters():
                gradient = parameter.grad
                if gradient is None or scanned >= _SCAN_ELEMENTS:
                    continue
                gradient = gradient.detach()
                if hasattr(gradient, "to_local"):
                    gradient = gradient.to_local()
                flat = gradient.view(-1)
                for offset in range(0, flat.numel(), 1 << 20):
                    if scanned >= _SCAN_ELEMENTS:
                        break
                    chunk = flat[offset : offset + (1 << 20)]
                    chunk = chunk[: _SCAN_ELEMENTS - scanned].float()
                    mask = torch.isfinite(chunk)
                    part_totals = torch.stack(
                        (
                            mask.sum().double(),
                            torch.where(mask, chunk, 0).square().sum().double(),
                        )
                    )
                    totals = part_totals if totals is None else totals + part_totals
                    scanned += chunk.numel()
                    if time.thread_time_ns() - started > 20_000_000:
                        self.emit.emit(
                            "capability",
                            {
                                "collector": "gradient_health",
                                "status": "self_disabled",
                                "reason": "cpu_budget",
                            },
                        )
                        self._disabled = True
                        return False
        # Single host sync for the whole scan.
        finite, squared = totals.tolist() if totals is not None else (0, 0.0)
        payload = {
            "collector": "gradient_health",
            "step": step,
            "finite_count": int(finite),
            "nonfinite_count": scanned - int(finite),
            "norm": squared**0.5,
        }
        if scanned >= _SCAN_ELEMENTS:
            payload["status"] = "partial"
            payload["reason"] = "element_budget"
        self.emit.emit("diagnostic", payload)
        return True

    def _report_skipped(self, reason: str) -> None:
        for collector in ("gradient_health", "active_diagnostics"):
            self.emit.emit(
                "capability",
                {"collector": collector, "status": "unavailable", "reason": reason},
            )

    def close(self) -> None:
        self._comm.stop()
        if not self._sampled and not self._disabled:
            self._report_skipped("step_threshold_not_reached")
        if self._timing is not None:
            self._timing.close()
        self._tensors = None
