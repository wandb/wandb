from types import ModuleType, SimpleNamespace


def test_supported_integration_preserves_step_and_is_idempotent(tmp_path, monkeypatch):
    import gc
    import sys
    import weakref

    from wandb.sdk.provenance.framework.torchtitan import TorchTitanIntegration
    from wandb.sdk.provenance.patching import PatchRegistry

    class Trainer:
        def train_step(self, iterator):
            return next(iterator) * 2

    Trainer.__module__ = "torchtitan.trainer"
    package = tmp_path / "torchtitan"
    package.mkdir()
    git = tmp_path / ".git"
    git.mkdir()
    (git / "HEAD").write_text("6b3b7d4" + "0" * 33)
    events = []
    modules = {
        "torchtitan": SimpleNamespace(__file__=str(package / "__init__.py")),
        "torchtitan.trainer": SimpleNamespace(Trainer=Trainer),
    }
    emit = SimpleNamespace(emit=lambda kind, payload: events.append((kind, payload)))
    integration = TorchTitanIntegration(modules, emit, 0)
    registry = PatchRegistry()
    forbidden_calls = []

    def forbidden(*args, **kwargs):
        forbidden_calls.append(True)
        raise AssertionError("Level 0 invoked a collective or active diagnostic")

    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(
            cuda=SimpleNamespace(is_initialized=lambda: False),
            distributed=SimpleNamespace(
                all_reduce=forbidden,
                all_gather=forbidden,
                barrier=forbidden,
                broadcast=forbidden,
            ),
            isfinite=forbidden,
            mm=forbidden,
        ),
    )
    integration.install(registry)
    integration.install(registry)
    trainer = Trainer()
    trainer.engine = SimpleNamespace(num_completed_steps=0)
    assert trainer.train_step(iter([3])) == 6
    assert [kind for kind, _ in events].count("step") == 1
    reference = weakref.ref(trainer)
    del trainer
    gc.collect()
    assert reference() is None
    assert not integration._states
    assert not forbidden_calls
    registry.detach()


def test_unknown_revision_keeps_training_unwrapped(tmp_path):
    from wandb.sdk.provenance.framework.torchtitan import TorchTitanIntegration
    from wandb.sdk.provenance.patching import PatchRegistry

    class Trainer:
        def train_step(self):
            return 7

    original = Trainer.train_step
    events = []
    modules = {
        "torchtitan": SimpleNamespace(
            __file__=str(tmp_path / "torchtitan" / "__init__.py")
        ),
        "torchtitan.trainer": SimpleNamespace(Trainer=Trainer),
    }
    integration = TorchTitanIntegration(
        modules,
        SimpleNamespace(emit=lambda kind, payload: events.append((kind, payload))),
        0,
    )
    integration.install(PatchRegistry())
    integration.install(PatchRegistry())
    assert Trainer.train_step is original
    assert len(events) == 1
    assert events[0][1]["reason"] == "unsupported_integration"


def _observed(tmp_path, monkeypatch, module_name, owner):
    import sys

    from wandb.sdk.provenance.framework.torchtitan import TorchTitanIntegration
    from wandb.sdk.provenance.patching import PatchRegistry

    owner.__module__ = module_name
    package = tmp_path / "torchtitan"
    package.mkdir()
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("6b3b7d4" + "0" * 33)
    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(cuda=SimpleNamespace(is_initialized=lambda: False)),
    )
    events = []
    modules = {
        "torchtitan": SimpleNamespace(__file__=str(package / "__init__.py")),
        module_name: ModuleType(module_name),
    }
    setattr(modules[module_name], owner.__name__, owner)
    emit = SimpleNamespace(emit=lambda kind, payload: events.append((kind, payload)))
    registry = PatchRegistry()
    integration = TorchTitanIntegration(modules, emit, 0)
    integration.install(registry)
    return events, registry, integration


def test_checkpoint_records_only_executed_saves_at_the_completed_step(
    tmp_path, monkeypatch
):
    import pytest

    class TrainingEngine:
        def __init__(self):
            self.num_completed_steps = 0
            self.fail = False

        def optim_step(self):
            self.num_completed_steps += 1

        def save_checkpoint(self, *, last_step=False):
            if self.fail:
                raise OSError("disk full")
            return self.num_completed_steps % 2 == 0

    events, registry, _ = _observed(
        tmp_path, monkeypatch, "torchtitan.training_engine", TrainingEngine
    )
    engine = TrainingEngine()
    for _ in range(4):
        engine.optim_step()
        engine.save_checkpoint()
    engine.fail = True
    with pytest.raises(OSError):
        engine.save_checkpoint()
    registry.detach()
    checkpoints = [payload for kind, payload in events if kind == "checkpoint"]
    assert [(p["step"], p.get("status")) for p in checkpoints] == [
        (2, None),
        (4, None),
        (4, "partial"),
    ]


def test_data_wait_names_its_step_only_after_a_consecutive_log(tmp_path, monkeypatch):
    class MetricsProcessor:
        def __init__(self):
            self.data_loading_times = []

        def log(self, step, loss):
            self.data_loading_times.clear()

    events, registry, _ = _observed(
        tmp_path, monkeypatch, "torchtitan.observability.metrics", MetricsProcessor
    )
    metrics = MetricsProcessor()
    for step in (1, 2, 4):
        metrics.data_loading_times.append(0.5)
        metrics.log(step, 1.0)
    registry.detach()
    waits = [p for kind, p in events if kind == "phase" and p["phase"] == "data_wait"]
    assert [(p.get("step"), p["duration_ms"]) for p in waits] == [
        (1, 500.0),
        (2, 500.0),
        (None, 500.0),
    ]


def test_close_lifecycle_is_emitted_before_finish_tears_down_the_writer(
    tmp_path, monkeypatch
):
    class Trainer:
        def close(self):
            self.finish()

    events, registry, integration = _observed(
        tmp_path, monkeypatch, "torchtitan.trainer", Trainer
    )
    closed = []
    trainer = Trainer()
    trainer.engine = SimpleNamespace(num_completed_steps=5)

    def finish():
        integration.close()
        closed.append(sum(p.get("event") == "close" for _, p in events))

    trainer.finish = finish
    trainer.close()
    other = Trainer()
    other.engine = SimpleNamespace(num_completed_steps=5)
    other.finish = lambda: None
    other.close()
    registry.detach()
    closes = [p for kind, p in events if kind == "lifecycle" and p["event"] == "close"]
    assert len(closes) == 2
    assert closed == [1]
    assert all(p["step"] == 6 for p in closes)
