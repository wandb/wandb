from __future__ import annotations

import enum
import importlib.abc
import os
import sys
from typing import Any

from .events import EventEmitter
from .identity import launch_identity
from .patching import PatchRegistry


class BootstrapState(enum.Enum):
    DISABLED = "disabled"
    ARMED = "armed"
    ACTIVE = "active"
    UNSUPPORTED = "unsupported"


state = BootstrapState.DISABLED
level: int | None = None
emitter: EventEmitter | None = None
_registry = PatchRegistry()
_installed = False
_hook_seen = False
_attached: Any = None
_integration: Any = None
rank_ready = False


def status() -> str:
    return state.value if _hook_seen else "startup_hook_missing"


class _Loader(importlib.abc.Loader):
    def __init__(self, original):
        self.original = original

    def create_module(self, spec):
        method = getattr(self.original, "create_module", None)
        return method(spec) if method else None

    def exec_module(self, module):
        self.original.exec_module(module)
        try:
            _after_import()
        except Exception:
            pass

    def __getattr__(self, name):
        return getattr(self.original, name)


class _Finder(importlib.abc.MetaPathFinder):
    names = frozenset(
        (
            "torch.cuda",
            "torch.distributed",
            "torchtitan",
            "torchtitan.trainer",
            "torchtitan.training_engine",
            "torchtitan.observability.metrics",
        )
    )

    def find_spec(self, fullname, path=None, target=None):
        if fullname not in self.names:
            return None
        for finder in sys.meta_path:
            if isinstance(finder, _Finder) or not hasattr(finder, "find_spec"):
                continue
            spec = finder.find_spec(fullname, path, target)
            if spec is not None:
                if spec.loader is not None:
                    spec.loader = _Loader(spec.loader)
                return spec
        return None


def install() -> None:
    global _installed, _hook_seen, level, state
    if _installed:
        return
    raw = os.environ.get("WANDB_X_PROVENANCE_LEVEL")
    if raw not in ("0", "1"):
        return
    try:
        _hook_seen = True
        level = int(raw)
        state = BootstrapState.ARMED
        if level == 1:
            from .level1 import install_level1_bootstrap

            install_level1_bootstrap()
        sys.meta_path.insert(0, _Finder())
        _installed = True
        from .run import install_wandb_init_interceptor

        install_wandb_init_interceptor()
        _after_import()
    except Exception:
        state = BootstrapState.UNSUPPORTED


def _distributed_ready(context) -> None:
    global rank_ready
    rank_ready = True
    from .run import ensure_shared_run

    ensure_shared_run()
    # A failed attempt still gets a writer so its restart is visible.
    if context.error is not None and emitter is not None:
        payload = {
            "event": "init_process_group",
            "status": "partial",
            "reason": "attempt_failed",
            "source": "bootstrap",
        }
        max_restarts = os.environ.get("TORCHELASTIC_MAX_RESTARTS", "")
        if max_restarts.isdigit():
            payload["max_restarts"] = int(max_restarts)
        emitter.emit("lifecycle", payload)


def _device_selected(context) -> None:
    if context.error is not None or emitter is None:
        return
    from .binding import binding_evidence

    cuda = sys.modules.get("torch.cuda")
    if cuda is not None:
        emitter.emit("binding", binding_evidence(cuda, os.environ))


def _after_import() -> None:
    global _integration
    if state not in (BootstrapState.ARMED, BootstrapState.ACTIVE):
        return
    distributed = sys.modules.get("torch.distributed")
    if distributed is not None and hasattr(distributed, "init_process_group"):
        _registry.observe(distributed, "init_process_group", after=_distributed_ready)
    cuda = sys.modules.get("torch.cuda")
    if cuda is not None and hasattr(cuda, "set_device"):
        _registry.observe(cuda, "set_device", after=_device_selected)
    if emitter is not None:
        from .framework.torchtitan import TorchTitanIntegration

        if _integration is None:
            _integration = TorchTitanIntegration(sys.modules, emitter, level)
        _integration.install(_registry)


def attach_run(run: Any) -> None:
    global emitter, _attached, state, level, _installed
    run_level = run._settings.x_provenance_level
    # Env activation waits for init_process_group so helpers never become writers.
    if run_level is None or _attached is not None or (_hook_seen and not rank_ready):
        return
    try:
        identity = launch_identity(os.environ)
        if identity is None:
            return
        if not _installed:
            state = BootstrapState.ARMED
            sys.meta_path.insert(0, _Finder())
            _installed = True
        import json

        from wandb.proto import wandb_internal_pb2 as pb
        from wandb.sdk.wandb_run import TeardownHook, TeardownStage

        interface = run._interface
        request = pb.ProvenanceStartRequest(
            protocol_version=2,
            level=run_level,
            run_id=run.id,
            rank=identity.rank,
            local_rank=identity.local_rank,
            node_rank=identity.node_rank,
            attempt=identity.attempt,
            primary=identity.rank == 0,
            identity_json=json.dumps(
                {"world_size": identity.world_size, "scheduler": identity.scheduler}
            ).encode(),
        )
        response = interface.deliver_provenance_start(request).wait_or(timeout=5)
        if (
            not response.accepted
            or response.protocol_version != 2
            or not response.writer_id
        ):
            state = BootstrapState.UNSUPPORTED
            return
        level = run_level
        emitter = EventEmitter(interface, response.writer_id)
        _attached = run
        state = BootstrapState.ACTIVE
        run._teardown_hooks.append(
            TeardownHook(lambda: finish_run(run), TeardownStage.EARLY)
        )
        _after_import()
        from .plugins import load_test_plugins

        load_test_plugins(_registry, emitter)
        if level == 1:
            import threading

            from .platform import enrich

            threading.Thread(
                target=enrich,
                args=(emitter,),
                name="wandb-provenance-platform",
                daemon=True,
            ).start()
    except Exception:
        state = BootstrapState.UNSUPPORTED


def finish_run(run: Any) -> None:
    global state, _attached, _integration, emitter
    if run is not _attached:
        return
    for action in (
        _integration.close if _integration is not None else None,
        emitter.close if emitter is not None else None,
        _registry.detach,
    ):
        try:
            if action is not None:
                action()
        except Exception:
            pass
    _attached = _integration = emitter = None
    state = BootstrapState.DISABLED
