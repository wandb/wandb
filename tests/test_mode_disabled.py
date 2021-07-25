"""
disabled mode test.
"""

from __future__ import division

import pytest  # type: ignore

import wandb
import pickle
import os


def test_disabled_noop(test_settings):
    """Make sure that all objects are dummy objects in noop case."""
    run = wandb.init(mode="disabled", settings=test_settings)
    run.log(dict(this=2))
    run.finish()


def test_disabled_ops(test_settings):
    run = wandb.init(mode="disabled", settings=test_settings)
    print(len(run))
    print(abs(run))
    print(~run)
    print(run + 10)
    print(run - 10)
    print(run * 10)
    print(run / 1.2)
    print(run // 10)
    print(run % 10)
    print(run ** 10)
    print(run << 10)
    print(run >> 10)
    print(run & 2)
    print(run ^ 2)
    print(run | 2)
    print(+run)
    print(-run)
    run += 1
    run -= 1
    run *= 1
    run /= 1.2
    run //= 1
    run **= 1
    run <<= 1
    run >>= 1
    run |= 1
    run %= 1
    run ^= 1
    run &= 1
    run()
    print(run.attrib)
    print(run["item"])
    run["3"] = 3
    print(run["3"])
    print(run[3])
    print(int(run))
    print(float(run))
    print(run < 2)
    print(run <= 2)
    print(run == 2)
    print(run > 2)
    print(run >= 2)
    print(run != 2)
    print(run)
    print(str(run))
    print(repr(run))
    if run:
        print(run)
    print(bool(run))


def test_disabled_dir(test_settings, mocker):
    tmp_dir = "/tmp/dir"
    mocker.patch("tempfile.gettempdir", lambda: tmp_dir)
    run = wandb.init(mode="disabled", settings=test_settings)
    assert run.dir == tmp_dir


def test_disabled_summary(test_settings):
    run = wandb.init(mode="disabled", settings=test_settings)
    run.summary["cat"] = 2
    run.summary["nested"] = dict(level=3)
    print(run.summary["cat"])
    print(run.summary.cat)
    with pytest.raises(KeyError):
        print(run.summary["dog"])
    assert run.summary["nested"]["level"] == 3


def test_disabled_can_pickle():
    """Will it pickle?"""
    # This case comes up when using wandb in disabled mode, with keras
    # https://wandb.atlassian.net/browse/WB-3981
    obj = wandb.wandb_sdk.lib.RunDisabled()
    with open("test.pkl", "wb") as file:
        pickle.dump(obj, file)
    os.remove("test.pkl")


def test_disabled_globals(test_settings):
    # Test wandb.* attributes
    run = wandb.init(
        config={"foo": {"bar": {"x": "y"}}}, mode="disabled", settings=test_settings
    )
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


def test_bad_url(test_settings):
    s = wandb.Settings(mode="disabled", base_url="localhost:9000")
    test_settings._apply_settings(s)
    run = wandb.init(settings=test_settings)
    run.log({"acc": 0.9})
    wandb.join()


def test_login(test_settings):
    s = wandb.Settings(mode="disabled")
    test_settings._apply_settings(s)
    wandb.setup(test_settings)
    wandb.login("")


def test_no_dirs(test_settings, runner):
    with runner.isolated_filesystem():
        s = wandb.Settings(mode="disabled")
        test_settings._apply_settings(s)
        run = wandb.init(settings=test_settings)
        run.log({"acc": 0.9})
        run.finish()
        assert not os.path.isdir("wandb")
