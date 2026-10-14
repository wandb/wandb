from __future__ import annotations

import functools
import os
import re
import sys
import threading
import time
from typing import Any

from .comm_stats import CommStatsReporter, collective_family, fr_buffer_setting
from .timing import CudaEventQueue

_SCAN_TENSORS = 64
_GEMM_SIZE = 2048
_CPU_BUDGET_NS = 20_000_000
_MAPS = "/proc/self/maps"
_IB_CLASS = "/sys/class/infiniband"
_MAPS_LIMIT = 4 << 20
_PLUGIN_FAMILIES = ("tcpxo", "tcpx", "efa")
_SUFFIX = re.compile(r"[A-Z_]{1,48}")
_NUMBER = re.compile(r"-?[0-9]{1,10}")
# Clear of torch's own hook ids ('FREC', 'NANC').
_HOOK_ID = 0x57414E44


def install_level1_bootstrap() -> None:
    if "torch.distributed" in sys.modules:
        return
    name, size = fr_buffer_setting()
    if name is None:
        os.environ["TORCH_FR_BUFFER_SIZE"] = str(size)
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
        # TorchTitan graph wrappers seen so far; None until the first forward_backward.
        self._graphs: list[Any] | None = None
        self._capture: dict[str, Any] | None = None
        self._schedules = 0
        self._schedule_disabled = False
        self._replaying = False
        self._capability("nccl_sweep", "unsupported", "unsupported_boundary")

    def _communication(self, status, collectives, lost, read):
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
        self.emit.account(cpu_ns=read.cpu_ns, transient_bytes=read.dump_bytes)
        # A read with nothing new keeps the last state; available needs emitted records.
        if status != self._recorder and (collectives or status != "ok"):
            self._recorder = status
        window = {
            "read_id": read.read_id,
            "window_end_unix_ms": read.end_ns // 1_000_000,
        }
        if read.start_ns is not None:
            window["window_start_unix_ms"] = read.start_ns // 1_000_000
        # Loss belongs to the read, so only the read's capability record carries it.
        if self._recorder is not None or read.backoff_s is not None or self._replaying:
            payload = {
                "collector": "flight_recorder",
                "status": "partial",
                "lost_count": lost,
                **window,
            }
            if read.backoff_s is not None:
                payload["reason"] = "backed_off"
                payload["interval_s"] = read.backoff_s
            elif self._replaying:
                # Replayed graphs bypass c10d, so the recorder sees eager steps only.
                payload["reason"] = "cuda_graph_replay"
            elif self._recorder == "ok":
                payload["status"] = "available"
            else:
                payload["reason"] = self._recorder
                if self._recorder == "no_recognized_collectives":
                    payload["count"] = sum(c.count for c in collectives)
            self.emit.emit("capability", payload, wall_time_ns=read.end_ns)
        for collective in collectives:
            payload = {
                "collective": collective.name,
                "count": collective.count,
                "timed_count": collective.n_timed,
                **window,
            }
            for field in ("p50_ms", "p99_ms", "max_ms", "total_ms", "bytes"):
                value = getattr(collective, field)
                if value is not None:
                    payload[field] = value
            self.emit.emit("communication", payload, wall_time_ns=read.end_ns)

    def before_forward_backward(self, engine, step: int) -> None:
        """Watches c10d ops while a TorchTitan CUDA graph is still to be captured."""
        graphs = self._graphs
        if self._capture is not None or self._schedule_disabled or graphs == []:
            return
        if graphs and all(w._graph is not None for w in graphs):
            return
        graphs = self._wrappers()
        capture: dict[str, Any] = {
            "step": step,
            # Warm-up calls run eagerly, so a step holding them is not fully replayed.
            "mixed": not graphs or any(w._warmup_remaining for w in graphs),
            "ready": [w for w in graphs if w._graph is not None],
            "ops": {},
            "groups": [],
            "cpu_ns": 0,
            "failed": False,
        }
        started = time.thread_time_ns()
        try:
            torch = sys.modules["torch"]
            capturing = torch.cuda.is_current_stream_capturing
            ops = capture["ops"]

            def record(group, args):
                # Errors would surface in the user's collective; the hook map is in use.
                try:
                    if not capturing():
                        return
                    began = time.thread_time_ns()
                    family = collective_family(args.name.name)
                    op = ops.setdefault(family, [0, 0, set()])
                    op[0] += 1
                    op[1] += sum(
                        t.numel() * t.element_size() for t in args.input_tensors
                    )
                    op[2].add(group)
                    capture["cpu_ns"] += time.thread_time_ns() - began
                except Exception:
                    capture["failed"] = True

            self._capture = capture
            # Hook maps are unlocked; CPU-only groups may be busy on checkpoint threads.
            for index, group in enumerate(
                list(torch.distributed.distributed_c10d._world.pg_map)
            ):
                if any(d.type == "cuda" for d in group._device_types):
                    group.register_pre_hook(_HOOK_ID, functools.partial(record, index))
                    capture["groups"].append(group)
        except Exception:
            self._capture = None
            self._release(capture)
            self._fail_schedule()
        finally:
            self.emit.account(cpu_ns=time.thread_time_ns() - started)

    def after_forward_backward(self, engine) -> None:
        """Publishes the schedule a capture in this call recorded."""
        capture, self._capture = self._capture, None
        if capture is None:
            return
        started = time.thread_time_ns()
        self._release(capture)
        if capture["failed"]:
            self._fail_schedule()
            self.emit.account(cpu_ns=time.thread_time_ns() - started)
            return
        try:
            captured = any(
                w._graph is not None and all(w is not r for r in capture["ready"])
                for w in self._wrappers()
            )
            if not captured:
                return
            self._replaying = True
            self._schedules += 1
            replays = getattr(engine, "num_accumulation_steps", 1)
            if not getattr(engine, "_cuda_graph_per_accumulation_group_enabled", False):
                replays = 1
            window = {
                "schedule_id": self._schedules,
                "effective_from_step": capture["step"] + int(capture["mixed"]),
            }
            self.emit.emit(
                "capability",
                {
                    "collector": "communication_schedule",
                    "status": "available",
                    **window,
                },
            )
            for family, (count, nbytes, groups) in sorted(capture["ops"].items()):
                self.emit.emit(
                    "communication_schedule",
                    {
                        **window,
                        "collective": family,
                        "count_per_step": count * replays,
                        "bytes_per_step": nbytes * replays,
                        "group_count": len(groups),
                        "replays_per_step": replays,
                        "source": "cuda_graph_capture",
                    },
                )
        except Exception:
            self._fail_schedule()
        finally:
            self.emit.account(
                cpu_ns=time.thread_time_ns() - started + capture["cpu_ns"]
            )

    def _wrappers(self) -> list[Any]:
        # TorchTitan registers each wrapper on first call and forgets it at teardown.
        module = sys.modules.get("torchtitan.distributed.cuda_graph")
        known = self._graphs or []
        wrappers = getattr(getattr(module, "_manager", None), "_wrappers", ())
        self._graphs = known + [w for w in wrappers if all(w is not k for k in known)]
        return self._graphs

    @staticmethod
    def _release(capture: dict[str, Any] | None) -> None:
        for group in capture["groups"] if capture else ():
            try:
                group.unregister_pre_hook(_HOOK_ID)
            except Exception:
                pass

    def _fail_schedule(self) -> None:
        if not self._schedule_disabled:
            self._schedule_disabled = True
            self._capability(
                "communication_schedule", "self_disabled", "collector_failure"
            )

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
        started = time.thread_time_ns()
        try:
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
                                (_GEMM_SIZE, _GEMM_SIZE),
                                0.01,
                                device=engine.device,
                                dtype=torch.float16,
                            )
                            for _ in range(3)
                        )
                        self.emit.account(held_bytes=3 * _GEMM_SIZE**2 * 2)
                        self._timing = CudaEventQueue(
                            lambda: torch.cuda.Event(enable_timing=True), capacity=4
                        )
                        # Untimed first call keeps cuBLAS setup out of GEMM time.
                        torch.mm(
                            self._tensors[0], self._tensors[1], out=self._tensors[2]
                        )
                        self._capability("active_diagnostics", "available", None)
                    token = self._timing.start("gemm", step)
                    if token is not None:
                        torch.mm(
                            self._tensors[0], self._tensors[1], out=self._tensors[2]
                        )
                        self._timing.finish(token)
                except Exception:
                    self._gemm_disabled = True
                    self._capability(
                        "active_diagnostics", "self_disabled", "collector_failure"
                    )
        finally:
            self.emit.account(cpu_ns=time.thread_time_ns() - started)

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
        self._release(self._capture)
        self._capture = None
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
