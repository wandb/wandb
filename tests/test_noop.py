"""noop tests"""


from __future__ import print_function
import pytest
import wandb


def test_noop():
    run = wandb.init(config={"foo": {"bar": {"x": "y"}}}, mode="disabled")
    wandb.log({"x": {"y": "z"}})
    wandb.log({"foo": {"bar": {"x": "y"}}})
    assert wandb.run == run
    assert wandb.config == run.config
    assert wandb.summary == run.summary
    assert run.config.foo["bar"]["x"] == "y"
    assert wandb.summary["x"].y == "z"
    assert wandb.summary["foo"].bar.x == "y"
    wandb.summary.foo["bar"].update({"a": "b"})
    assert wandb.summary.foo.bar.a == "b"


def test_bad_url(test_settings):
    s = wandb.Settings(mode="disabled", base_url="localhost:9000")
    test_settings._apply_settings(s)
    run = wandb.init(settings=test_settings)
    run.log({"acc": 0.9})
    wandb.join()


if __name__ == "__main__":
    pytest.main([__file__])
