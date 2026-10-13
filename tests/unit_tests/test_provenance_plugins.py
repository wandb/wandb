from types import SimpleNamespace

import pytest


class Emitter:
    def __init__(self):
        self.events = []

    def emit(self, kind, payload):
        self.events.append((kind, payload))


def test_collection_level_alone_never_loads_plugins(monkeypatch):
    from wandb.sdk.provenance import plugins
    from wandb.sdk.provenance.patching import PatchRegistry

    monkeypatch.delenv("WANDB_X_PROVENANCE_SCENARIO", raising=False)
    monkeypatch.setenv("WANDB_X_PROVENANCE_LEVEL", "1")

    def forbidden(**kwargs):
        raise AssertionError("plugin discovery")

    monkeypatch.setattr(plugins.metadata, "entry_points", forbidden)
    emitter = Emitter()
    plugins.load_test_plugins(PatchRegistry(), emitter)
    assert emitter.events == []


def test_unallowlisted_plugin_never_imports(monkeypatch):
    from wandb.sdk.provenance import plugins
    from wandb.sdk.provenance.patching import PatchRegistry

    monkeypatch.setenv("WANDB_X_PROVENANCE_SCENARIO", "scenario.json")
    monkeypatch.setenv("WANDB_X_PROVENANCE_TEST_PLUGINS", "trusted")

    def forbidden():
        raise AssertionError("untrusted import")

    entry = SimpleNamespace(dist=SimpleNamespace(name="untrusted"), load=forbidden)
    monkeypatch.setattr(plugins.metadata, "entry_points", lambda **kwargs: [entry])
    emitter = Emitter()
    plugins.load_test_plugins(PatchRegistry(), emitter)
    assert len(emitter.events) == 1
    assert emitter.events[0][1]["status"] == "unavailable"


@pytest.mark.parametrize("count", [0, 2])
def test_missing_or_duplicate_allowed_plugins_are_not_loaded(monkeypatch, count):
    from wandb.sdk.provenance import plugins
    from wandb.sdk.provenance.patching import PatchRegistry

    monkeypatch.setenv("WANDB_X_PROVENANCE_SCENARIO", "scenario.json")
    monkeypatch.setenv("WANDB_X_PROVENANCE_TEST_PLUGINS", "trusted")

    def forbidden():
        pytest.fail("ambiguous entrypoint imported")

    entry = SimpleNamespace(dist=SimpleNamespace(name="trusted"), load=forbidden)
    monkeypatch.setattr(
        plugins.metadata, "entry_points", lambda **kwargs: [entry] * count
    )
    emitter = Emitter()
    plugins.load_test_plugins(PatchRegistry(), emitter)
    assert len(emitter.events) == 1
    assert emitter.events[0][1]["status"] == "unavailable"


def test_raising_plugin_reports_one_capability_and_training_survives(monkeypatch):
    from wandb.sdk.provenance import plugins
    from wandb.sdk.provenance.patching import PatchRegistry

    monkeypatch.setenv("WANDB_X_PROVENANCE_SCENARIO", "scenario.json")
    monkeypatch.setenv("WANDB_X_PROVENANCE_TEST_PLUGINS", "trusted")

    class Trainer:
        def step(self):
            return 7

    class Plugin:
        def register(self, registry, emit):
            def observer(context):
                raise RuntimeError("observer error")

            registry.observe(Trainer, "step", before=observer)
            raise RuntimeError("registration error")

    entry = SimpleNamespace(dist=SimpleNamespace(name="trusted"), load=lambda: Plugin)
    monkeypatch.setattr(plugins.metadata, "entry_points", lambda **kwargs: [entry])
    emitter = Emitter()
    registry = PatchRegistry()
    plugins.load_test_plugins(registry, emitter)
    assert Trainer().step() == 7
    assert len(emitter.events) == 1
    assert emitter.events[0][1]["status"] == "self_disabled"
    registry.detach()
