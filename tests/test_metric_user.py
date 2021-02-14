"""
metric user tests.
"""

import pytest
import wandb


def test_metric_run_none(user_test):
    run = user_test.get_run()
    run.log(dict(this=1))
    run.log(dict(that=2))

    r = user_test.get_records()
    assert len(r.records) == 2
    assert len(r.history) == 2
    assert len(r.summary) == 0


def test_metric_run_invalid_name(user_test):
    run = user_test.get_run()
    with pytest.raises(wandb.Error):
        run.define_metric("")


def test_metric_run_invalid_stepmetric(user_test):
    run = user_test.get_run()
    with pytest.raises(wandb.Error):
        run.define_metric("junk", step_metric=1)


def test_metric_run_invalid_glob(user_test):
    run = user_test.get_run()
    with pytest.raises(wandb.Error):
        run.define_metric("*invalidprefix", step_metric=1)


def test_metric_run_invalid_summary(user_test):
    run = user_test.get_run()
    with pytest.raises(wandb.Error):
        run.define_metric("metric", summary="doesnotexist")


def test_metric_run_ignored_extraargs(user_test, capsys):
    run = user_test.get_run()
    run.define_metric("junk", extra=1, another=2)
    captured = capsys.readouterr()
    print("GOT out", captured.out)
    print("GOT err", captured.err)
    assert "Unhandled define_metric() arg: extra" in captured.err
    assert "Unhandled define_metric() arg: another" in captured.err


def test_metric_prop_name(user_test):
    run = user_test.get_run()
    m = run.define_metric("metric")
    assert m.name == "metric"


def test_metric_prop_stepmetric(user_test):
    run = user_test.get_run()
    m = run.define_metric("metric", step_metric="globalstep")
    assert m.step_metric == "globalstep"


def test_metric_prop_stepmetric(user_test):
    run = user_test.get_run()
    m = run.define_metric("metric", step_metric="globalstep", step_sync=True)
    assert m.step_sync is True
    m2 = run.define_metric("metric2", step_metric="globalstep")
    assert not m2.step_sync


def test_metric_prop_summary(user_test):
    run = user_test.get_run()
    m = run.define_metric("metric", summary="min,max")
    assert m.summary == ("min", "max")
