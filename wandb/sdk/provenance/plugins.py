from __future__ import annotations

import os
from importlib import metadata
from typing import Protocol

from .events import EventEmitter
from .patching import PatchRegistry


class ProvenanceTestPlugin(Protocol):
    name: str

    def register(self, registry: PatchRegistry, emit: EventEmitter) -> None: ...


def load_test_plugins(registry: PatchRegistry, emit: EventEmitter) -> None:
    if not os.environ.get("WANDB_X_PROVENANCE_SCENARIO"):
        return
    allowed = {
        name.strip().lower().replace("_", "-")
        for name in os.environ.get("WANDB_X_PROVENANCE_TEST_PLUGINS", "").split(",")
        if name.strip()
    }
    try:
        entries = list(metadata.entry_points(group="wandb.provenance_test_plugin"))
        candidates = {name: [] for name in allowed}
        for entry in entries:
            name = entry.dist.name.lower().replace("_", "-") if entry.dist else ""
            if name in candidates:
                candidates[name].append(entry)
        if not allowed or any(len(group) != 1 for group in candidates.values()):
            emit.emit(
                "capability",
                {
                    "collector": "test_plugin",
                    "status": "unavailable",
                    "reason": "plugin_not_unique_or_missing",
                },
            )
            return
        for group in candidates.values():
            plugin = group[0].load()
            if isinstance(plugin, type):
                plugin = plugin()
            plugin.register(registry, emit)
    except Exception:
        emit.emit(
            "capability",
            {
                "collector": "test_plugin",
                "status": "self_disabled",
                "reason": "plugin_failure",
            },
        )
