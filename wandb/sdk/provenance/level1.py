from __future__ import annotations

import os
import re
import sys
import threading
import time
from typing import Any

from .comm_stats import CommStatsReporter
from .timing import CudaEventQueue

_SCAN_TENSORS = 64
_CPU_BUDGET_NS = 20_000_000
_MAPS = "/proc/self/maps"
_IB_CLASS = "/sys/class/infiniband"
_MAPS_LIMIT = 4 << 20
_PLUGIN_FAMILIES = ("tcpxo", "tcpx", "efa")
_SUFFIX = re.compile(r"[A-Z_]{1,48}")
_NUMBER = re.compile(r"-?[0-9]{1,10}")


def install_level1_bootstrap() -> None:
    if "torch.distributed" in sys.modules:
        return
    if (
        "TORCH_FR_BUFFER_SIZE" not in os.environ
        and "TORCH_NCCL_TRACE_BUFFER_SIZE" not in os.environ
    ):
        os.environ["TORCH_NCCL_TRACE_BUFFER_SIZE"] = "2000"
    # Recorder entries carry durations only when NCCL timing is on.
    os.environ.setdefault("TORCH_NCCL_ENABLE_TIMING", "1")


def _family(value: str) -> str:
    value = value.lower()
    if "fastrak" in value or "tcpxo" in value:
        return "tcpxo"
    if "tcpx" in value:
        return "tcpx"
    if "ofi" in value or "fabric" in value or "efa" in value:
        return "efa"
    if value == "ib" or "gib" in value or "net-ib" in value:
        return "ib"
    return "socket" if value == "socket" else "other"


def _loaded_family(ib_disabled: bool) -> tuple[str | None, bool]:
    found, nccl, truncated = set(), False, False
    try:
        with open(_MAPS, "rb") as maps:
            data = maps.read(_MAPS_LIMIT + 1)
        truncated = len(data) > _MAPS_LIMIT
    except OSError:
        data = None
    for line in (data or b"")[:_MAPS_LIMIT].splitlines():
        fields = line.split(maxsplit=5)
        if len(fields) < 6:
            continue
        path = fields[5].decode(errors="replace").lower()
        name = path.rsplit("/", 1)[-1]
        if name.startswith("libnccl.so"):
            nccl = True
        elif name.startswith("libnccl-net") or "fastrak" in name:
            found.add(_family(path))
    loaded = next((f for f in (*_PLUGIN_FAMILIES, "ib", "other") if f in found), None)
    # libibverbs loads on hosts without InfiniBand, so only an RDMA device means IB.
    if loaded is None and nccl and not ib_disabled:
        try:
            with os.scandir(_IB_CLASS) as devices:
                if next(devices, None) is not None:
                    loaded = "ib"
        except OSError:
            pass
    if loaded is None and nccl and not truncated:
        loaded = "socket"
    return loaded, truncated


class Level1Collectors:
    def __init__(self, emit: Any) -> None:
        self.emit = emit
        self._comm = CommStatsReporter(self._communication, 60)
        self._last_step = -100
        self._tensors = None
        self._timing = None
        self._host = None
        self._disabled = False
        self._gradient_disabled = False
        self._gemm_disabled = False
        self._gradient_pending: tuple[int, Any, Any, int, bool] | None = None
        self._gradient_samples = 0
        self._gradient_reported = False
        self._transport_started = False
        self._sampled = False
        self._cuda_reported = False
        self._recorder: str | None = None
        self._capability("nccl_sweep", "unsupported", "unsupported_boundary")

    def _communication(self, status, collectives, lost):
        if status == "unavailable":
            self._capability("flight_recorder", "unavailable", "recorder_unavailable")
            self._recorder = None
            return
        # The count is the buffer size or the read's CPU milliseconds.
        if status in ("buffer_too_large", "cpu_budget"):
            self.emit.emit(
                "capability",
                {
                    "collector": "flight_recorder",
                    "status": "partial"
                    if status == "buffer_too_large"
                    else "self_disabled",
                    "reason": status,
                    "count": lost,
                },
            )
            return
        # A read with nothing new keeps the last state; available needs emitted records.
        if status != self._recorder and (collectives or status == "recorder_empty"):
            self._recorder = status
            c10d = getattr(
                getattr(sys.modules.get("torch"), "_C", None), "_distributed_c10d", None
            )
            payload = {"collector": "flight_recorder", "status": "partial"}
            if not hasattr(c10d, "_dump_nccl_trace"):
                # The generic dump may not hold the recorder NCCL writes to.
                payload["reason"] = "generic_recorder"
            elif status == "ok":
                payload["status"] = "available"
            elif status == "no_recognized_collectives":
                payload["reason"] = status
                payload["count"] = sum(c.count for c in collectives)
            else:
                payload["reason"] = status
            self.emit.emit("capability", payload)
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

    def _capability(self, collector: str, status: str, reason: str | None) -> None:
        payload = {"collector": collector, "status": status}
        if reason:
            payload["reason"] = reason
        self.emit.emit("capability", payload)

    def step(self, engine, step: int) -> None:
        if self._disabled:
            return
        self._comm.maybe_start()
        if not self._transport_started:
            self._transport_started = True
            threading.Thread(
                target=self._transport, name="wandb-provenance-transport", daemon=True
            ).start()
        pending = self._gradient_pending
        if pending is not None and pending[1].query():
            self._gradient_pending = None
            self._report_gradients(pending[0], pending[2].tolist(), *pending[3:])
        if self._timing is not None and not self._gemm_disabled:
            for phase in self._timing.completed():
                if phase.duration_ms > 100:
                    self._gemm_disabled = True
                    self._capability(
                        "active_diagnostics", "self_disabled", "gpu_budget"
                    )
                    break
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
            self._disabled = True
            for collector in ("gradient_health", "active_diagnostics"):
                self._capability(collector, "self_disabled", "queue_pressure")
            return
        torch = sys.modules.get("torch")
        if torch is None or not torch.cuda.is_initialized():
            if not self._cuda_reported:
                self._cuda_reported = True
                self._report_skipped("cuda_unavailable")
            return
        with torch.no_grad():
            if not self._gradient_disabled and self._gradient_pending is None:
                try:
                    self._scan_gradients(torch, engine, step)
                except Exception:
                    self._gradient_disabled = True
                    self._capability(
                        "gradient_health", "self_disabled", "collector_failure"
                    )
            if self._gemm_disabled:
                return
            try:
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
                    # Untimed first call, so cuBLAS setup is not measured as GEMM time.
                    torch.mm(self._tensors[0], self._tensors[1], out=self._tensors[2])
                    self._capability("active_diagnostics", "available", None)
                token = self._timing.start("gemm", step)
                if token is not None:
                    torch.mm(self._tensors[0], self._tensors[1], out=self._tensors[2])
                    self._timing.finish(token)
            except Exception:
                self._gemm_disabled = True
                self._capability(
                    "active_diagnostics", "self_disabled", "collector_failure"
                )

    def _scan_gradients(self, torch, engine, step: int) -> None:
        started = time.thread_time_ns()
        parameters = [p for part in engine.model_parts for p in part.parameters()]
        # A fixed stride keeps the sampled tensors and their norm comparable.
        stride = max(1, -(-len(parameters) // _SCAN_TENSORS))
        gradients = []
        for parameter in parameters[::stride]:
            gradient = parameter.grad
            if gradient is None:
                continue
            gradient = gradient.detach()
            if hasattr(gradient, "to_local"):
                gradient = gradient.to_local()
            if gradient.numel():
                gradients.append(gradient)
        if not gradients:
            return
        try:
            norms = torch._foreach_norm(gradients, 2, dtype=torch.float32)
        except (AttributeError, TypeError, RuntimeError):
            norms = [
                torch.linalg.vector_norm(gradient, dtype=torch.float32)
                for gradient in gradients
            ]
        norms = torch.stack(norms)
        finite = torch.isfinite(norms)
        totals = torch.stack(
            (
                finite.logical_not().sum().double(),
                torch.where(finite, norms, 0).double().square().sum(),
            )
        )
        if totals.is_cuda:
            # Harvested on a later step, so the scan never waits for the GPU.
            if self._host is None:
                self._host = torch.empty(2, dtype=torch.float64, pin_memory=True)
            self._host.copy_(totals, non_blocking=True)
            event = torch.cuda.Event()
            event.record()
            self._gradient_pending = (
                step,
                event,
                self._host,
                len(gradients),
                stride > 1,
            )
        else:
            self._report_gradients(step, totals.tolist(), len(gradients), stride > 1)
        self._gradient_samples += 1
        # The first sample pays one-time kernel setup, so it is not charged.
        if (
            self._gradient_samples > 1
            and time.thread_time_ns() - started > _CPU_BUDGET_NS
        ):
            self._gradient_disabled = True
            self._capability("gradient_health", "self_disabled", "cpu_budget")

    def _report_gradients(self, step, totals, tensors: int, sampled: bool) -> None:
        nonfinite, squared = totals
        if not self._gradient_reported:
            self._gradient_reported = True
            self._capability("gradient_health", "available", None)
        payload = {
            "collector": "gradient_health",
            "step": step,
            "count": tensors,
            "finite_count": tensors - int(nonfinite),
            "nonfinite_count": int(nonfinite),
            "norm": squared**0.5,
        }
        if sampled:
            payload["status"] = "partial"
            payload["reason"] = "tensor_sample"
        self.emit.emit("diagnostic", payload)

    def _transport(self) -> None:
        try:
            env = {}
            for name in ("NCCL_NET", "NCCL_NET_PLUGIN"):
                value = os.environ.get(name)
                if value is not None:
                    none = name == "NCCL_NET_PLUGIN" and value.strip().lower() == "none"
                    env[name] = "none" if none else _family(value.strip())
            if _NUMBER.fullmatch(os.environ.get("NCCL_IB_DISABLE", "")):
                env["NCCL_IB_DISABLE"] = os.environ["NCCL_IB_DISABLE"]
            for name in sorted(os.environ):
                prefix = next(
                    (
                        p
                        for p in ("NCCL_GPUDIRECTTCPX_", "NCCL_FASTRAK_")
                        if name.startswith(p)
                    ),
                    None,
                )
                if (
                    prefix is None
                    or len(env) >= 32
                    or not _SUFFIX.fullmatch(name[len(prefix) :])
                ):
                    continue
                value = os.environ[name]
                # Interface names and paths are reduced to presence.
                numeric = _NUMBER.fullmatch(value) and not any(
                    part in name for part in ("IFNAME", "DEV", "BINDINGS", "PREFIX")
                )
                env[name] = value if numeric else "set"
            configured = next(
                (
                    env[name]
                    for name in ("NCCL_NET", "NCCL_NET_PLUGIN")
                    if env.get(name) not in (None, "none", "other")
                ),
                None,
            )
            if configured is None and any(n.startswith("NCCL_FASTRAK_") for n in env):
                configured = "tcpxo"
            if configured is None and any(
                n.startswith("NCCL_GPUDIRECTTCPX_") for n in env
            ):
                configured = "tcpx"

            loaded, truncated = _loaded_family(env.get("NCCL_IB_DISABLE") == "1")

            payload: dict[str, Any] = {
                "collector": "nccl_transport",
                "status": "partial",
                "source": "proc_maps+nccl_env",
                "configured": configured or "none",
                "loaded": loaded or "unknown",
            }
            if env:
                payload["nccl_env"] = env
            # An unnamed plugin path is consistent with a configured plugin family.
            agrees = loaded == configured or (
                loaded == "other" and configured in _PLUGIN_FAMILIES
            )
            if configured and agrees:
                evidence = (
                    configured,
                    "configured_and_loaded",
                    "configured_and_loaded",
                )
            elif configured and (
                loaded in (None, "other") or configured in ("socket", "ib")
            ):
                evidence = (configured, "configured", "configured_only")
            elif configured:
                evidence = (loaded, "loaded", "configured_not_loaded")
            elif loaded not in (None, "other"):
                evidence = (loaded, "loaded", "loaded_only")
            else:
                evidence = None
                payload["status"] = "unavailable"
                payload["reason"] = (
                    "unrecognized_plugin"
                    if loaded == "other"
                    else "maps_truncated"
                    if truncated
                    else "no_evidence"
                )
            if evidence is not None:
                (
                    payload["transport"],
                    payload["confidence"],
                    payload["reason"],
                ) = evidence
            self.emit.emit("capability", payload)
        except Exception:
            self._capability("nccl_transport", "unavailable", "collector_failure")

    def _report_skipped(self, reason: str) -> None:
        for collector in ("gradient_health", "active_diagnostics"):
            self._capability(collector, "unavailable", reason)

    def close(self) -> None:
        self._comm.stop()
        if not self._sampled and not self._disabled:
            self._report_skipped("step_threshold_not_reached")
        if not self._transport_started:
            self._capability(
                "nccl_transport", "unavailable", "step_threshold_not_reached"
            )
        if self._timing is not None:
            self._timing.close()
        self._tensors = None
        self._host = None
        self._gradient_pending = None
