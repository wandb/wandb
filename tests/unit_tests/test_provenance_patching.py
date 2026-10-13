import gc
import inspect
import weakref

import pytest


def test_wrapper_preserves_results_exceptions_and_signature():
    from wandb.sdk.provenance.patching import PatchRegistry

    class Trainer:
        def step(self, value, *, fail=False):
            if fail:
                raise ValueError("user failure")
            return value * 2

    original = inspect.signature(Trainer.step)
    seen = []
    registry = PatchRegistry()

    def after(context):
        seen.append((context.result, context.error))
        raise RuntimeError("observer failure")

    registry.observe(Trainer, "step", after=after)
    registry.observe(Trainer, "step", after=after)
    trainer = Trainer()
    assert trainer.step(3) == 6
    assert len(seen) == 1
    with pytest.raises(ValueError, match="user failure"):
        trainer.step(3, fail=True)
    assert isinstance(seen[-1][1], ValueError)
    assert inspect.signature(Trainer.step) == original
    reference = weakref.ref(trainer)
    del trainer
    seen.clear()
    gc.collect()
    assert reference() is None


def test_static_and_class_methods_keep_descriptors():
    from wandb.sdk.provenance.patching import PatchRegistry

    class Owner:
        @staticmethod
        def static(value):
            return value + 1

        @classmethod
        def klass(cls):
            return cls

    registry = PatchRegistry()
    registry.observe(Owner, "static", after=lambda ctx: None)
    registry.observe(Owner, "klass", after=lambda ctx: None)
    assert Owner.static(2) == 3
    assert Owner().static(2) == 3
    assert Owner.klass() is Owner


def test_hook_does_not_swallow_keyboard_interrupt():
    from wandb.sdk.provenance.patching import PatchRegistry

    class Trainer:
        def step(self):
            return "done"

    def before(context):
        raise KeyboardInterrupt

    registry = PatchRegistry()
    registry.observe(Trainer, "step", before=before)
    with pytest.raises(KeyboardInterrupt):
        Trainer().step()
