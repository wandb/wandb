"""
metric user tests.
"""

import pytest
import wandb

from wandb.proto import wandb_internal_pb2 as pb


def test_metric_run_none(user_test):
    run = user_test.get_run()
    run.log(dict(this=1))
    run.log(dict(that=2))

    r = user_test.get_records()
    assert len(r.records) == 2
    assert len(r.history) == 2


def test_metric_run_metric_obj(user_test):
    run = user_test.get_run()
    m1 = run.define_metric("glob")
    m2 = run.define_metric("val", step_metric=m1)
    assert m2.step_metric == "glob"

    r = user_test.get_records()
    assert len(r.records) == 2
    assert len(r.metric) == 2

    mr1, mr2 = r.metric
    glob_metric = pb.MetricRecord(name="glob")
    glob_metric.options.defined = True
    step_metric = pb.MetricRecord(name="val", step_metric="glob")
    step_metric.options.defined = True
    step_metric.options.step_sync = True
    assert mr1 == glob_metric
    assert mr2 == step_metric


def test_metric_run_hide(user_test):
    run = user_test.get_run()
    m = run.define_metric("glob", hidden=True)
    assert m.hidden is True

    r = user_test.get_records()
    assert len(r.records) == 1
    assert len(r.metric) == 1


def test_metric_run_goal(user_test):
    run = user_test.get_run()
    m1 = run.define_metric("glob", goal="maximize")
    assert m1.goal == "maximize"
    m2 = run.define_metric("glob", goal="minimize")
    assert m2.goal == "minimize"
    with pytest.raises(wandb.Error):
        run.define_metric("m2", goal="nothing")

    r = user_test.get_records()
    assert len(r.records) == 2
    assert len(r.metric) == 2


def test_metric_run_invalid_name(user_test):
    run = user_test.get_run()
    with pytest.raises(wandb.Error):
        run.define_metric("")

    r = user_test.get_records()
    assert len(r.records) == 0


def test_metric_run_invalid_stepmetric(user_test):
    run = user_test.get_run()
    with pytest.raises(wandb.Error):
        run.define_metric("junk", step_metric=1)

    r = user_test.get_records()
    assert len(r.records) == 0


def test_metric_run_invalid_glob(user_test):
    run = user_test.get_run()
    with pytest.raises(wandb.Error):
        run.define_metric("*invalidprefix")

    r = user_test.get_records()
    assert len(r.records) == 0


def test_metric_run_invalid_summary(user_test):
    run = user_test.get_run()
    with pytest.raises(wandb.Error):
        run.define_metric("metric", summary="doesnotexist")

    r = user_test.get_records()
    assert len(r.records) == 0


def test_metric_run_ignored_extraargs(user_test, capsys):
    run = user_test.get_run()
    run.define_metric("junk", extra=1, another=2)
    captured = capsys.readouterr()
    print("GOT out", captured.out)
    print("GOT err", captured.err)
    assert "Unhandled define_metric() arg: extra" in captured.err
    assert "Unhandled define_metric() arg: another" in captured.err

    r = user_test.get_records()
    assert len(r.records) == 1
    assert len(r.metric) == 1


def test_metric_prop_name(user_test):
    run = user_test.get_run()
    m = run.define_metric("metric")
    assert m.name == "metric"

    r = user_test.get_records()
    assert len(r.records) == 1
    assert len(r.metric) == 1


def test_metric_prop_stepmetric(user_test):
    run = user_test.get_run()
    m1 = run.define_metric("metric", step_metric="globalstep")
    assert m1.step_metric == "globalstep"
    m2 = run.define_metric("metric")
    assert not m2.step_metric

    r = user_test.get_records()
    assert len(r.records) == 2
    assert len(r.metric) == 2


def test_metric_prop_stepsync(user_test):
    run = user_test.get_run()
    m = run.define_metric("metric", step_metric="globalstep", step_sync=True)
    assert m.step_sync is True
    m2 = run.define_metric("metric2", step_metric="globalstep")
    # default is true when step_metric is set
    assert m2.step_sync
    m3 = run.define_metric("metric3", step_metric="globalstep", step_sync=False)
    assert not m3.step_sync

    r = user_test.get_records()
    assert len(r.records) == 3
    assert len(r.metric) == 3


def test_metric_prop_summary(user_test):
    run = user_test.get_run()
    m1 = run.define_metric("metric", summary="min,max")
    assert m1.summary == ("min", "max")
    m2 = run.define_metric("metric")
    assert not m2.summary
    m3 = run.define_metric("metric", summary="best")
    assert m3.summary == ("best",)
    m4 = run.define_metric("metric", summary="mean")
    assert m4.summary == ("mean",)
    m5 = run.define_metric("metric", summary="")
    assert not m5.summary

    r = user_test.get_records()
    assert len(r.records) == 5
    assert len(r.metric) == 5


def test_metric_twice(user_test):
    run = user_test.get_run()
    m1a = run.define_metric("metric", summary="best,max", step_metric="thestep")
    m1b = run.define_metric("metric", summary="min")
    r = user_test.get_records()
    assert len(r.records) == 2
    assert len(r.metric) == 2
    # merging or overwriting happens in handler (internal)


def test_metric_twice_overwrite(user_test):
    run = user_test.get_run()
    m1a = run.define_metric("metric", summary="best,max", step_metric="thestep")
    m1b = run.define_metric("metric", summary="min", overwrite=True)
    r = user_test.get_records()
    assert len(r.records) == 2
    assert len(r.metric) == 2
    # merging or overwriting happens in handler (internal)
