"""metric internal tests."""

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


def test_metric_none(publish_util, mock_run, wandb_backend_spy):
    run = mock_run(use_magic_mock=True)
    history = _gen_history()
    publish_util(run=run, history=history)

    with wandb_backend_spy.freeze() as snapshot:
        summary = snapshot.summary(run_id=run.id)
        assert summary["v1"] == 2
        assert summary["v2"] == 3
        assert summary["v3"] == "pizza"
        assert summary["mystep"] == 3
        assert summary["_step"] == 2


def test_metric_step(publish_util, mock_run, wandb_backend_spy):
    run = mock_run(use_magic_mock=True)
    history = _gen_history()
    metrics = [
        pb.MetricRecord(glob_name="*", step_metric="mystep"),
    ]
    metrics = _make_metrics(metrics)
    publish_util(run=run, metrics=metrics, history=history)

    with wandb_backend_spy.freeze() as snapshot:
        summary = snapshot.summary(run_id=run.id)
        assert summary["v1"] == 2
        assert summary["v2"] == 3
        assert summary["v3"] == "pizza"
        assert summary["mystep"] == 3
        assert summary["_step"] == 2


def test_metric_max(publish_util, mock_run, wandb_backend_spy):
    run = mock_run(use_magic_mock=True)
    history = _gen_history()
    m1 = pb.MetricRecord(name="v2")
    m1.summary.max = True
    metrics = _make_metrics([m1])
    publish_util(run=run, metrics=metrics, history=history)

    with wandb_backend_spy.freeze() as snapshot:
        summary = snapshot.summary(run_id=run.id)
        assert summary["v1"] == 2
        assert summary["v2"] == {"max": 8}
        assert summary["v3"] == "pizza"
        assert summary["mystep"] == 3
        assert summary["_step"] == 2


def test_metric_min(publish_util, mock_run, wandb_backend_spy):
    run = mock_run(use_magic_mock=True)
    history = _gen_history()
    m1 = pb.MetricRecord(name="v2")
    m1.summary.min = True
    metrics = _make_metrics([m1])
    publish_util(run=run, metrics=metrics, history=history)

    with wandb_backend_spy.freeze() as snapshot:
        summary = snapshot.summary(run_id=run.id)
        assert summary["v1"] == 2
        assert summary["v2"] == {"min": 2}
        assert summary["v3"] == "pizza"
        assert summary["mystep"] == 3
        assert summary["_step"] == 2


def test_metric_min_str(publish_util, mock_run, wandb_backend_spy):
    run = mock_run(use_magic_mock=True)
    history = _gen_history()
    m1 = pb.MetricRecord(name="v3")
    m1.summary.min = True
    metrics = _make_metrics([m1])
    publish_util(run=run, metrics=metrics, history=history)

    with wandb_backend_spy.freeze() as snapshot:
        summary = snapshot.summary(run_id=run.id)
        assert summary["v1"] == 2
        assert summary["v2"] == 3
        assert summary["mystep"] == 3
        assert summary["_step"] == 2


def test_metric_sum_none(publish_util, mock_run, wandb_backend_spy):
    history = _gen_history()
    m1 = pb.MetricRecord(name="v2")
    metrics = _make_metrics([m1])
    run = mock_run(use_magic_mock=True)
    publish_util(run=run, history=history, metrics=metrics)

    with wandb_backend_spy.freeze() as snapshot:
        summary = snapshot.summary(run_id=run.id)
        assert summary["v1"] == 2
        assert summary["v2"] == 3
        assert summary["v3"] == "pizza"
        assert summary["mystep"] == 3
        assert summary["_step"] == 2


def test_metric_mult(publish_util, mock_run, wandb_backend_spy):
    history = _gen_history()
    m1 = pb.MetricRecord(name="mystep")
    m2 = pb.MetricRecord(name="v1", step_metric="mystep")
    m2.summary.max = True
    m3 = pb.MetricRecord(name="v2", step_metric="mystep")
    m3.summary.min = True
    metrics = _make_metrics([m1, m2, m3])
    run = mock_run(use_magic_mock=True)
    publish_util(run=run, history=history, metrics=metrics)

    with wandb_backend_spy.freeze() as snapshot:
        summary = snapshot.summary(run_id=run.id)
        assert summary["v1"] == {"max": 3}
        assert summary["v2"] == {"min": 2}
        assert summary["v3"] == "pizza"
        assert summary["mystep"] == 3
        assert summary["_step"] == 2


def test_metric_again(publish_util, mock_run, wandb_backend_spy):
    history = _gen_history()
    m1 = pb.MetricRecord(name="mystep")
    m2 = pb.MetricRecord(name="v1", step_metric="mystep")
    m3 = pb.MetricRecord(name="v2")
    m4 = pb.MetricRecord(name="v2", step_metric="mystep")
    metrics = _make_metrics([m1, m2, m3, m4])
    run = mock_run(use_magic_mock=True)
    publish_util(run=run, history=history, metrics=metrics)

    with wandb_backend_spy.freeze() as snapshot:
        summary = snapshot.summary(run_id=run.id)
        metrics = snapshot.metrics(run_id=run.id)

        assert summary["v1"] == 2
        assert summary["v2"] == 3
        assert summary["v3"] == "pizza"
        assert summary["mystep"] == 3
        assert summary["_step"] == 2
        assert metrics and len(metrics) == 3


def test_metric_mean(publish_util, mock_run, wandb_backend_spy):
    history = _gen_history()
    m1 = pb.MetricRecord(name="v2", step_metric="mystep")
    m1.summary.mean = True
    metrics = _make_metrics([m1])

    run = mock_run(use_magic_mock=True)
    publish_util(run=run, history=history, metrics=metrics)

    with wandb_backend_spy.freeze() as snapshot:
        summary = snapshot.summary(run_id=run.id)

        assert summary["v1"] == 2
        assert summary["v2"] == {"mean": 13.0 / 3}
        assert summary["v3"] == "pizza"
        assert summary["mystep"] == 3
        assert summary["_step"] == 2


def test_metric_stepsync(publish_util, mock_run, wandb_backend_spy):
    history = []
    history.append(
        dict(
            step=0,
            data=dict(
                a1=1,
            ),
        )
    )
    history.append(dict(step=1, data=dict(s1=2)))
    history.append(
        dict(
            step=2,
            data=dict(
                a1=3,
            ),
        )
    )
    history.append(dict(step=3, data=dict(a1=5, s1=4)))
    history.append(dict(step=3, data=dict(s1=6)))
    history.append(
        dict(
            step=4,
            data=dict(
                a1=7,
            ),
        )
    )
    history.append(dict(step=5, data=dict(a1=9, s1=8)))

    m0 = pb.MetricRecord(name="s1")
    m1 = pb.MetricRecord(name="a1", step_metric="s1")
    m1.options.step_sync = True

    metrics = _make_metrics([m0, m1])

    run = mock_run(use_magic_mock=True)
    publish_util(run=run, history=history, metrics=metrics)

    with wandb_backend_spy.freeze() as snapshot:
        summary = snapshot.summary(run_id=run.id)
        history = snapshot.history(run_id=run.id)

        assert summary["s1"] == 8
        assert summary["a1"] == 9
        assert summary["_step"] == 5

        a1_values = set(val["a1"] for val in history.values() if "a1" in val)
        s1_values = set(val["s1"] for val in history.values() if "s1" in val)
        assert a1_values == {1, 3, 5, 7, 9}
        assert s1_values == {2, 4, 6, 8}


def test_metric_twice_norm(publish_util, mock_run, wandb_backend_spy):
    m1a = pb.MetricRecord(name="metric")
    m1a.summary.best = True
    m1a.summary.max = True
    m1a.step_metric = "thestep"
    m1b = pb.MetricRecord(name="metric")
    m1b.summary.min = True

    metrics = _make_metrics([m1a, m1b])
    run = mock_run(use_magic_mock=True)
    publish_util(run=run, metrics=metrics)

    with wandb_backend_spy.freeze() as snapshot:
        metrics = snapshot.metrics(run_id=run.id)
        assert len(metrics) == 2
        assert metrics[0] == {"1": "thestep"}
        assert metrics[1] == {"1": "metric", "5": 1, "7": [1, 2, 4]}


def test_metric_twice_over(publish_util, mock_run, wandb_backend_spy):
    m1a = pb.MetricRecord(name="metric")
    m1a.summary.best = True
    m1a.summary.max = True
    m1a.step_metric = "thestep"
    m1b = pb.MetricRecord(name="metric")
    m1b.summary.min = True
    m1b._control.overwrite = True

    metrics = _make_metrics([m1a, m1b])
    run = mock_run(use_magic_mock=True)
    publish_util(run=run, metrics=metrics)

    with wandb_backend_spy.freeze() as snapshot:
        metrics = snapshot.metrics(run_id=run.id)
        assert len(metrics) == 2
        assert metrics[0] == {"1": "thestep"}
        assert metrics[1] == {"1": "metric", "7": [1]}


def test_metric_glob_twice_over(publish_util, mock_run, wandb_backend_spy):
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
    m1b._control.overwrite = True

    metrics = _make_metrics([m1a, m1b])

    run = mock_run(use_magic_mock=True)
    publish_util(run=run, metrics=metrics, history=history)

    with wandb_backend_spy.freeze() as snapshot:
        metrics = snapshot.metrics(run_id=run.id)
        summary = snapshot.summary(run_id=run.id)

        assert metrics and len(metrics) == 1
        assert metrics[0] == {"1": "metric", "7": [1]}

        assert summary["metric"] == {"min": 1}
        assert summary["_step"] == 0


def test_metric_nan_max(publish_util, mock_run, wandb_backend_spy):
    history = []
    history.append(dict(step=0, data=dict(v2=2)))
    history.append(dict(step=1, data=dict(v2=8)))
    history.append(dict(step=2, data=dict(v2=float("nan"))))

    m1 = pb.MetricRecord(name="v2")
    m1.summary.max = True
    metrics = _make_metrics([m1])

    run = mock_run(use_magic_mock=True)
    publish_util(run=run, metrics=metrics, history=history)

    with wandb_backend_spy.freeze() as snapshot:
        summary = snapshot.summary(run_id=run.id)
        assert summary["v2"] == {"max": 8}


def test_metric_dot_flat_escaped(publish_util, mock_run, wandb_backend_spy):
    """Match works when metric is escaped."""
    history = []
    history.append(dict(step=0, data={"this.has.dots": 2}))
    history.append(dict(step=1, data={"this.also": 2}))
    history.append(dict(step=2, data={"nodots": 2}))
    history.append(dict(step=3, data={"this.also": 1}))

    m1 = pb.MetricRecord(name=r"this\.also")
    m1.summary.max = True
    metrics = _make_metrics([m1])

    run = mock_run(use_magic_mock=True)
    publish_util(run=run, metrics=metrics, history=history)

    with wandb_backend_spy.freeze() as snapshot:
        metrics = snapshot.metrics(run_id=run.id)
        summary = snapshot.summary(run_id=run.id)

        assert metrics and len(metrics) == 1
        assert metrics[0] == {"1": r"this\.also", "7": [2]}

        assert summary["this.also"] == {"max": 2}
        assert summary["nodots"] == 2
        assert summary["this.has.dots"] == 2
        assert summary["_step"] == 3


def test_metric_dot_flat_notescaped(publish_util, mock_run, wandb_backend_spy):
    """Match doesn't work if metric is not escaped."""
    history = []
    history.append(dict(step=0, data={"this.has.dots": 2}))
    history.append(dict(step=1, data={"this.also": 2}))
    history.append(dict(step=2, data={"nodots": 2}))
    history.append(dict(step=3, data={"this.also": 1}))

    m1 = pb.MetricRecord(name="this.also")
    m1.summary.max = True
    metrics = _make_metrics([m1])

    run = mock_run(use_magic_mock=True)
    publish_util(run=run, metrics=metrics, history=history)

    with wandb_backend_spy.freeze() as snapshot:
        metrics = snapshot.metrics(run_id=run.id)
        summary = snapshot.summary(run_id=run.id)

        assert metrics and len(metrics) == 1
        assert metrics[0] == {"1": "this.also", "7": [2]}

        assert summary["this.also"] == 1
        assert summary["nodots"] == 2
        assert summary["this.has.dots"] == 2
        assert summary["_step"] == 3


def test_metric_dot_glob(publish_util, mock_run, wandb_backend_spy):
    """Glob escapes the defined metric name."""
    run = mock_run(use_magic_mock=True)
    history = []
    history.append(dict(step=0, data={"this.has.dots": 2}))
    history.append(dict(step=1, data={"this.also": 2}))
    history.append(dict(step=2, data={"nodots": 3}))
    history.append(dict(step=3, data={"this.also": 1}))

    m1 = pb.MetricRecord(name="this\\.also")
    m1.options.defined = True
    m1.summary.max = True
    m2 = pb.MetricRecord(glob_name="*")
    m2.options.defined = True
    m2.summary.min = True
    metrics = _make_metrics([m1, m2])
    publish_util(run=run, history=history, metrics=metrics)

    with wandb_backend_spy.freeze() as snapshot:
        metrics = snapshot.metrics(run_id=run.id)
        summary = snapshot.summary(run_id=run.id)

        assert metrics and len(metrics) == 3
        # order doesn't really matter
        assert metrics[0] == {"1": "this\\.also", "7": [2], "6": [3]}
        assert metrics[1] == {"1": "this\\.has\\.dots", "7": [1]}
        assert metrics[2] == {"1": "nodots", "7": [1]}
        assert summary["this.also"] == {"max": 2}
        assert summary["this.has.dots"] == {"min": 2}
        assert summary["nodots"] == {"min": 3}
        assert summary["_step"] == 3


def test_metric_best(publish_util, mock_run, wandb_backend_spy):
    run = mock_run(use_magic_mock=True)
    history = _gen_history()
    m1 = pb.MetricRecord(name="mystep")
    m2 = pb.MetricRecord(name="v1", step_metric="mystep")
    m2.summary.best = True
    m2.goal = m2.GOAL_MAXIMIZE
    m3 = pb.MetricRecord(name="v2", step_metric="mystep")
    m3.summary.best = True
    m3.goal = m3.GOAL_MINIMIZE
    metrics = _make_metrics([m1, m2, m3])
    publish_util(run=run, history=history, metrics=metrics)

    with wandb_backend_spy.freeze() as snapshot:
        summary = snapshot.summary(run_id=run.id)
        history = snapshot.history(run_id=run.id)
        print(summary)
        print(history)
        assert summary["v1"] == {"best": 3}
        assert summary["v2"] == {"best": 2}
        assert history[2]["v1"] == 2
        assert history[2]["v2"] == 3
        assert history[2]["v3"] == "pizza"
        assert history[2]["mystep"] == 3
        assert history[2]["_step"] == 2


def test_metric_glob_twice_norm(publish_util, mock_run, wandb_backend_spy):
    run = mock_run(use_magic_mock=True)
    _history = [dict(step=0, data=dict(metric=1))]

    m1a = pb.MetricRecord(glob_name="*")
    m1a.summary.best = True
    m1a.summary.max = True
    m1a.step_metric = "thestep"
    m1b = pb.MetricRecord(glob_name="*")
    m1b.summary.min = True

    _metrics = _make_metrics([m1a, m1b])
    publish_util(run=run, history=_history, metrics=_metrics)

    with wandb_backend_spy.freeze() as snapshot:
        summary = snapshot.summary(run_id=run.id)
        history = snapshot.history(run_id=run.id)
        metrics = snapshot.metrics(run_id=run.id)

        assert metrics and len(metrics) == 2
        assert metrics[0] == {"1": "thestep"}
        assert metrics[1] == {"1": "metric", "5": 1, "7": [1, 2, 4]}
        assert summary["metric"] == {"max": 1, "best": 1, "min": 1}
        assert history[0]["metric"] == 1
        assert history[0]["_step"] == 0
