"""disabled mode test."""

import os
from unittest import mock

import pytest  # type: ignore
import wandb


def test_disabled_noop(wandb_init):
    """Make sure that all objects are dummy objects in noop case."""
    run = wandb_init(mode="disabled")
    run.log(dict(this=2))
    run.finish()


def test_disabled_dir(wandb_init):
    wandb.setup()  # need to do it before we mock tempfile.gettempdir (for service)
    tmp_dir = "/tmp/dir"
    with mock.patch("tempfile.gettempdir", lambda: tmp_dir):
        run = wandb_init(mode="disabled")
    assert run.dir == tmp_dir


def test_disabled_summary(wandb_init):
    run = wandb_init(mode="disabled")
    run.summary["cat"] = 2
    run.summary["nested"] = dict(level=3)
    print(run.summary["cat"])
    print(run.summary.cat)
    with pytest.raises(KeyError):
        print(run.summary["dog"])
    assert run.summary["nested"]["level"] == 3


def test_disabled_globals(wandb_init):
    # Test wandb.* attributes
    run = wandb_init(config={"foo": {"bar": {"x": "y"}}}, mode="disabled")
    wandb.log({"x": {"y": "z"}})
    wandb.log({"foo": {"bar": {"x": "y"}}})
    assert wandb.run == run
    assert wandb.config == run.config
    assert wandb.summary == run.summary
    assert wandb.config.foo["bar"]["x"] == "y"
    assert wandb.summary["x"].y == "z"
    assert wandb.summary["foo"].bar.x == "y"
    wandb.summary.foo["bar"].update({"a": "b"})
    assert wandb.summary.foo.bar.a == "b"
    run.finish()


def test_bad_url(wandb_init):
    run = wandb_init(
        settings=dict(mode="disabled", base_url="http://my-localhost:9000")
    )
    run.log({"acc": 0.9})
    run.finish()


def test_no_dirs(wandb_init):
    run = wandb_init(settings={"mode": "disabled"})
    run.log({"acc": 0.9})
    run.finish()
    assert not os.path.isdir("wandb")
