"""
metric internal tests.
"""

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

    summary = ctx_util.summary

    assert {
        "v1": 2,
        "v1": {"best": 3},
        "v2": 3,
        "v2": {"best": 2},
        "v3": "pizza",
        "mystep": 3,
        "_step": 2,
    } == summary


def test_metric_glob_twice_norm(publish_util):
    history = []
    history.append(
        dict(
            step=0,
            data=dict(
                metric=1,
            ),
        )
    )

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
        "metric": {"best": 1, "max": 1, "min": 1},
    }
