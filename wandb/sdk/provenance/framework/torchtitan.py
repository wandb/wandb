from __future__ import annotations

import functools
import os
import sys
import time
import weakref

from ..binding import binding_evidence
from ..timing import CudaEventQueue
from . import versions

_RECORD_KINDS = {
    "train_step": "step",
    "save_checkpoint": "checkpoint",
    "load_checkpoint": "checkpoint",
    "train": "lifecycle",
}


class TorchTitanIntegration:
    def __init__(self, modules, emit, level=0) -> None:
        self.modules = modules
        self.emit = emit
        self.level = level
        self._installed = set()
        self._unsupported = False
        self._supported_reported = False
        self._states = weakref.WeakKeyDictionary()
        self._level1 = None
        self._closing = None

    def install(self, registry) -> None:
        if "torchtitan" not in self.modules:
            return
        revision = versions.revision(self.modules)
        if not revision or not revision.startswith(versions.SUPPORTED_COMMIT):
            if not self._unsupported:
                self._unsupported = True
                self.emit.emit(
                    "capability",
                    {
                        "collector": "torchtitan",
                        "status": "unsupported",
                        "reason": "unsupported_integration",
                    },
                )
            return
        routes = (
            ("torchtitan.trainer", "Trainer", ("train", "train_step", "close")),
            (
                "torchtitan.training_engine",
                "TrainingEngine",
                (
                    "forward_backward",
                    "optim_step",
                    "save_checkpoint",
                    "load_checkpoint",
                ),
            ),
            ("torchtitan.observability.metrics", "MetricsProcessor", ("log",)),
        )
        metrics_module = self.modules.get("torchtitan.observability.metrics")
        key = (metrics_module, "compute_training_performance_metrics")
        if (
            metrics_module is not None
            and key not in self._installed
            and hasattr(metrics_module, key[1])
        ):
            registry.observe(
                metrics_module,
                key[1],
                after=functools.partial(self._after, "performance"),
            )
            self._installed.add(key)
        for module_name, class_name, methods in routes:
            module = self.modules.get(module_name)
            owner = getattr(module, class_name, None)
            if not isinstance(owner, type) or owner.__module__ != module_name:
                continue
            for name in methods:
                key = (owner, name)
                if key in self._installed or not hasattr(owner, name):
                    continue
                registry.observe(
                    owner,
                    name,
                    before=functools.partial(self._before, name),
                    after=functools.partial(self._after, name),
                )
                self._installed.add(key)
        if self._installed and not self._supported_reported:
            self._supported_reported = True
            self.emit.emit(
                "capability",
                {"collector": "torchtitan", "status": "available", "source": revision},
            )
        if self.level == 1 and self._level1 is None:
            from ..level1 import Level1Collectors

            self._level1 = Level1Collectors(self.emit)

    def _before(self, name, context) -> None:
        instance = context.instance
        state = self._states.setdefault(
            instance, {"pending": {}, "timing": None, "binding": None, "logged": None}
        )
        engine = getattr(instance, "engine", instance)
        step = getattr(engine, "num_completed_steps", None)
        if isinstance(step, int):
            # A save checkpoints the step that just completed.
            step = step if name == "save_checkpoint" else step + 1
        else:
            step = None
        if name == "optim_step" and self._level1 is not None and step is not None:
            self._level1.step(engine, step)
        token = None
        torch = sys.modules.get("torch")
        cuda = getattr(torch, "cuda", None)
        if (
            name in ("forward_backward", "optim_step")
            and cuda is not None
            and cuda.is_initialized()
        ):
            if state["timing"] is None:
                state["timing"] = CudaEventQueue(lambda: cuda.Event(enable_timing=True))
            token = state["timing"].start(name, step)
        state["pending"][context.started_ns] = (token, step)
        if name == "close":
            self._closing = (context.started_ns, step)
        if name == "train_step" and cuda is not None and cuda.is_initialized():
            index = cuda.current_device()
            if state["binding"] != index:
                state["binding"] = index
                self.emit.emit("binding", binding_evidence(cuda, os.environ))
        if name == "log":
            self._log(instance, state, context)

    def _log(self, instance, state, context) -> None:
        payload = {}
        for key, value in zip(("step", "loss"), context.args[:2], strict=False):
            if type(value) in (int, float):
                payload[key] = value
        for original, key in (("step", "step"), ("global_avg_loss", "loss")):
            value = context.kwargs.get(original)
            if type(value) in (int, float):
                payload[key] = value
        extra = context.kwargs.get("extra_metrics")
        if isinstance(extra, dict) and type(extra.get("n_tokens_seen")) in (
            int,
            float,
        ):
            payload["cumulative_tokens"] = extra["n_tokens_seen"]
        for attr, key in (
            ("num_flops_per_token", "flops"),
            ("ntokens_since_last_log", "tokens"),
        ):
            value = getattr(instance, attr, None)
            if type(value) in (int, float):
                payload[key] = value
        waits = getattr(instance, "data_loading_times", None)
        if (
            isinstance(waits, list)
            and waits
            and all(type(value) in (int, float) for value in waits)
        ):
            wait = {
                "phase": "data_wait",
                "duration_ms": sum(waits) * 1000,
                "source": "framework_metrics",
            }
            logged = payload.get("step")
            # Waits cover all steps since the previous log.
            if type(logged) is int and state["logged"] in (None, logged - 1):
                wait["step"] = logged
            self.emit.emit("phase", wait)
        state["logged"] = payload.get("step")
        if payload:
            self.emit.emit("metrics", payload)

    def _after(self, name, context) -> None:
        if name == "performance":
            if context.error is None and isinstance(context.result, dict):
                payload = {
                    key: value
                    for key, value in context.result.items()
                    if key in ("tokens_per_second", "tflops", "mfu_percent")
                    and type(value) in (int, float)
                }
                if payload:
                    self.emit.emit("metrics", payload)
            return
        state = self._states.get(context.instance)
        if state is None:
            return
        token, step = state["pending"].pop(context.started_ns, (None, None))
        timing = state["timing"]
        if timing is not None:
            timing.finish(token)
            for completed in timing.completed():
                payload = {
                    "phase": completed.phase,
                    "duration_ms": completed.duration_ms,
                    "source": "cuda_event",
                }
                if completed.step is not None:
                    payload["step"] = completed.step
                self.emit.emit("phase", payload)
        payload = {
            "event": name,
            "duration_ms": (time.monotonic_ns() - context.started_ns) / 1e6,
            "source": "cpu_clock",
        }
        if step is not None:
            payload["step"] = step
        if context.error is not None:
            payload["status"] = "partial"
            payload["reason"] = "framework_exception"
        engine = getattr(context.instance, "engine", context.instance)
        parallel = getattr(engine, "parallelism_context", None)
        try:
            meshes = parallel.get_all_one_dimensional_meshes()
            for axis in ("dp_shard", "dp_replicate", "tp", "pp", "cp", "ep"):
                mesh = meshes.get(axis)
                if mesh is not None:
                    payload[axis] = int(mesh.get_local_rank())
        except Exception:
            pass
        kind = _RECORD_KINDS.get(name)
        # TorchTitan calls save every step; False means nothing was written.
        unsaved = name == "save_checkpoint" and not context.result
        if kind is not None:
            if context.error is not None or not unsaved:
                self.emit.emit(kind, payload)
        elif name not in ("log", "close") and timing is None:
            payload["phase"] = name
            self.emit.emit("phase", payload)
        if name == "close":
            self.close()

    def close(self) -> None:
        # Rank 0's wandb.finish runs inside Trainer.close, before its after-hook.
        closing, self._closing = self._closing, None
        if closing is not None:
            started_ns, step = closing
            payload = {
                "event": "close",
                "duration_ms": (time.monotonic_ns() - started_ns) / 1e6,
                "source": "cpu_clock",
            }
            if step is not None:
                payload["step"] = step
            self.emit.emit("lifecycle", payload)
        dropped = 0
        for state in self._states.values():
            if state["timing"] is not None:
                state["timing"].close()
                dropped += state["timing"].dropped
        if dropped:
            self.emit.emit(
                "capability",
                {
                    "collector": "cuda_timing",
                    "status": "partial",
                    "reason": "pending_events_at_shutdown",
                    "count": dropped,
                },
            )
        if self._level1 is not None:
            self._level1.close()
