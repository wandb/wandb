"""
metric internal tests.
"""

from __future__ import print_function

import math

from wandb.proto import wandb_internal_pb2 as pb


def _gen_history():
    history = []
    history.append(dict(step=0, data=dict(v1=1, v2=2, v3="dog", mystep=1)))
    history.append(dict(step=1, data=dict(v1=3, v2=8, v3="cat", mystep=2)))
    history.append(dict(step=2, data=dict(v1=2, v2=3, v3="pizza", mystep=3)))
    return history


def _make_metrics(mitems):
    metrics = []
    for mitem in mitems:
        m = pb.MetricRecord()
        m.CopyFrom(mitem)
        metrics.append(m)
    return metrics


def test_metric_none(publish_util):
    history = _gen_history()
    ctx_util = publish_util(history=history)
    summary = ctx_util.summary

    # TODO(jhr): remove these when UI updated
    assert "x_axis" not in ctx_util.config_wandb

    assert dict(v1=2, v2=3, v3="pizza", mystep=3, _step=2) == summary


def test_metric_step(publish_util):
    history = _gen_history()
    metrics = [
        pb.MetricRecord(glob_name="*", step_metric="mystep"),
    ]
    metrics = _make_metrics(metrics)
    ctx_util = publish_util(history=history, metrics=metrics)

    config_wandb = ctx_util.config_wandb
    summary = ctx_util.summary

    # TODO(jhr): remove these when UI updated
    assert "x_axis" in config_wandb
    assert "mystep" in config_wandb["x_axis"]

    assert dict(v1=2, v2=3, v3="pizza", mystep=3, _step=2) == summary


def test_metric_max(publish_util):
    history = _gen_history()
    m1 = pb.MetricRecord(name="v2")
    m1.summary.max = True
    metrics = _make_metrics([m1])
    ctx_util = publish_util(history=history, metrics=metrics)

    config_wandb = ctx_util.config_wandb
    summary = ctx_util.summary

    # TODO(jhr): remove these when UI updated
    assert "x_axis" not in config_wandb

    assert {
        "v1": 2,
        "v2": 3,
        "v2.max": 8,
        "v3": "pizza",
        "mystep": 3,
        "_step": 2,
    } == summary


def test_metric_min(publish_util):
    history = _gen_history()
    m1 = pb.MetricRecord(name="v2")
    m1.summary.min = True
    metrics = _make_metrics([m1])
    ctx_util = publish_util(history=history, metrics=metrics)

    config_wandb = ctx_util.config_wandb
    summary = ctx_util.summary

    # TODO(jhr): remove these when UI updated
    assert "x_axis" not in config_wandb

    assert {
        "v1": 2,
        "v2": 3,
        "v2.min": 2,
        "v3": "pizza",
        "mystep": 3,
        "_step": 2,
    } == summary


def test_metric_min_str(publish_util):
    history = _gen_history()
    m1 = pb.MetricRecord(name="v3")
    m1.summary.min = True
    metrics = _make_metrics([m1])
    ctx_util = publish_util(history=history, metrics=metrics)

    config_wandb = ctx_util.config_wandb
    summary = ctx_util.summary

    # TODO(jhr): remove these when UI updated
    assert "x_axis" not in config_wandb

    assert {"v1": 2, "v2": 3, "v3": "pizza", "mystep": 3, "_step": 2,} == summary


def test_metric_sum_none(publish_util):
    history = _gen_history()
    m1 = pb.MetricRecord(name="v2")
    metrics = _make_metrics([m1])
    ctx_util = publish_util(history=history, metrics=metrics)

    config_wandb = ctx_util.config_wandb
    summary = ctx_util.summary

    # TODO(jhr): remove these when UI updated
    assert "x_axis" not in config_wandb

    assert {"v1": 2, "v2": 3, "v3": "pizza", "mystep": 3, "_step": 2,} == summary


def test_metric_mult(publish_util):
    history = _gen_history()
    m1 = pb.MetricRecord(name="mystep")
    m2 = pb.MetricRecord(name="v1", step_metric="mystep")
    m2.summary.max = True
    m3 = pb.MetricRecord(name="v2", step_metric="mystep")
    m3.summary.min = True
    metrics = _make_metrics([m1, m2, m3])
    ctx_util = publish_util(history=history, metrics=metrics)

    config_wandb = ctx_util.config_wandb
    summary = ctx_util.summary

    # TODO(jhr): remove these when UI updated
    assert "x_axis" in config_wandb
    assert "mystep" in config_wandb["x_axis"]

    assert {
        "v1": 2,
        "v1.max": 3,
        "v2": 3,
        "v2.min": 2,
        "v3": "pizza",
        "mystep": 3,
        "_step": 2,
    } == summary


def test_metric_best(publish_util):
    history = _gen_history()
    m1 = pb.MetricRecord(name="mystep")
    m2 = pb.MetricRecord(name="v1", step_metric="mystep")
    m2.summary.best = True
    m2.goal = m2.GOAL_MAXIMIZE
    m3 = pb.MetricRecord(name="v2", step_metric="mystep")
    m3.summary.best = True
    m3.goal = m3.GOAL_MINIMIZE
    metrics = _make_metrics([m1, m2, m3])
    ctx_util = publish_util(history=history, metrics=metrics)

    config_wandb = ctx_util.config_wandb
    summary = ctx_util.summary

    assert {
        "v1": 2,
        "v1.best": 3,
        "v2": 3,
        "v2.best": 2,
        "v3": "pizza",
        "mystep": 3,
        "_step": 2,
    } == summary


def test_metric_again(publish_util):
    history = _gen_history()
    m1 = pb.MetricRecord(name="mystep")
    m2 = pb.MetricRecord(name="v1", step_metric="mystep")
    m3 = pb.MetricRecord(name="v2")
    m4 = pb.MetricRecord(name="v2", step_metric="mystep")
    metrics = _make_metrics([m1, m2, m3, m4])
    ctx_util = publish_util(history=history, metrics=metrics)

    config_wandb = ctx_util.config_wandb
    summary = ctx_util.summary

    assert {"v1": 2, "v2": 3, "v3": "pizza", "mystep": 3, "_step": 2,} == summary

    metrics = ctx_util.metrics
    assert metrics and len(metrics) == 3


def test_metric_mean(publish_util):
    history = _gen_history()
    m1 = pb.MetricRecord(name="v2", step_metric="mystep")
    m1.summary.mean = True
    metrics = _make_metrics([m1])
    ctx_util = publish_util(history=history, metrics=metrics)

    config_wandb = ctx_util.config_wandb
    summary = ctx_util.summary

    assert {
        "v1": 2,
        "v2": 3,
        "v2.mean": 13.0 / 3,
        "v3": "pizza",
        "mystep": 3,
        "_step": 2,
    } == summary


def test_metric_stepsync(publish_util):
    history = []
    history.append(dict(step=0, data=dict(a1=1,)))
    history.append(dict(step=1, data=dict(s1=2)))
    history.append(dict(step=2, data=dict(a1=3,)))
    history.append(dict(step=3, data=dict(a1=5, s1=4)))
    history.append(dict(step=3, data=dict(s1=6)))
    history.append(dict(step=4, data=dict(a1=7,)))
    history.append(dict(step=5, data=dict(a1=9, s1=8)))

    m0 = pb.MetricRecord(name="s1")
    m1 = pb.MetricRecord(name="a1", step_metric="s1")
    m1.options.step_sync = True

    metrics = _make_metrics([m0, m1])
    ctx_util = publish_util(history=history, metrics=metrics)

    config_wandb = ctx_util.config_wandb
    summary = ctx_util.summary
    history = ctx_util.history

    assert {"a1": 9, "s1": 8, "_step": 5,} == summary

    history_val = [(h.get("a1"), h.get("s1")) for h in history if "a1" in h]
    assert history_val == [(1, None), (3, 2), (5, 4), (7, 6), (9, 8)]


def test_metric_twice_norm(publish_util):
    m1a = pb.MetricRecord(name="metric")
    m1a.summary.best = True
    m1a.summary.max = True
    m1a.step_metric = "thestep"
    m1b = pb.MetricRecord(name="metric")
    m1b.summary.min = True

    metrics = _make_metrics([m1a, m1b])
    ctx_util = publish_util(metrics=metrics)

    metrics = ctx_util.metrics
    assert len(metrics) == 2
    mstep, mmetric = metrics
    assert mstep == {"1": "thestep"}
    assert mmetric == {"1": "metric", "5": 1, "7": [1, 2, 4]}


def test_metric_twice_over(publish_util):
    m1a = pb.MetricRecord(name="metric")
    m1a.summary.best = True
    m1a.summary.max = True
    m1a.step_metric = "thestep"
    m1b = pb.MetricRecord(name="metric")
    m1b.summary.min = True
    m1b._control.overwrite = True

    metrics = _make_metrics([m1a, m1b])
    ctx_util = publish_util(metrics=metrics)

    metrics = ctx_util.metrics
    assert len(metrics) == 2
    mstep, mmetric = metrics
    assert mstep == {"1": "thestep"}
    assert mmetric == {"1": "metric", "7": [1]}


def test_metric_glob_twice_norm(publish_util):
    history = []
    history.append(dict(step=0, data=dict(metric=1,)))

    m1a = pb.MetricRecord(glob_name="*")
    m1a.summary.best = True
    m1a.summary.max = True
    m1a.step_metric = "thestep"
    m1b = pb.MetricRecord(glob_name="*")
    m1b.summary.min = True

    metrics = _make_metrics([m1a, m1b])
    ctx_util = publish_util(history=history, metrics=metrics)

    metrics = ctx_util.metrics
    summary = ctx_util.summary
    assert metrics and len(metrics) == 2
    mstep, mmetric = metrics
    assert mstep == {"1": "thestep"}
    assert mmetric == {"1": "metric", "5": 1, "7": [1, 2, 4]}
    assert summary == {
        "_step": 0,
        "metric": 1,
        "metric.best": 1,
        "metric.max": 1,
        "metric.min": 1,
    }


def test_metric_glob_twice_over(publish_util):
    history = []
    history.append(dict(step=0, data=dict(metric=1,)))

    m1a = pb.MetricRecord(glob_name="*")
    m1a.summary.best = True
    m1a.summary.max = True
    m1a.step_metric = "thestep"
    m1b = pb.MetricRecord(glob_name="*")
    m1b.summary.min = True
    m1b._control.overwrite = True

    metrics = _make_metrics([m1a, m1b])
    ctx_util = publish_util(history=history, metrics=metrics)

    metrics = ctx_util.metrics
    summary = ctx_util.summary
    assert metrics and len(metrics) == 1
    mmetric = metrics[0]
    assert mmetric == {"1": "metric", "7": [1]}
    assert summary == {"_step": 0, "metric": 1, "metric.min": 1}


def test_metric_nan_max(publish_util):
    history = []
    history.append(dict(step=0, data=dict(v2=2)))
    history.append(dict(step=1, data=dict(v2=8)))
    history.append(dict(step=2, data=dict(v2=float("nan"))))

    m1 = pb.MetricRecord(name="v2")
    m1.summary.max = True
    metrics = _make_metrics([m1])
    ctx_util = publish_util(history=history, metrics=metrics)

    config_wandb = ctx_util.config_wandb
    summary = ctx_util.summary

    assert math.isnan(summary.get("v2"))
    assert summary.get("v2.max") == 8
