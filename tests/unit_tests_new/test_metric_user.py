"""
metric user tests.
"""

import pytest
import wandb
from wandb.proto import wandb_internal_pb2 as pb


def test_metric_none(mock_run, parse_records, record_q):
    run = mock_run()
    run.log(dict(this=1))
    run.log(dict(that=2))

    parsed = parse_records(record_q)
    assert len(parsed.records) == 2
    history = parsed.history or parsed.partial_history
    assert len(history) == 2


def test_metric_run_metric_obj(mock_run, parse_records, record_q):
    run = mock_run()
    metric_1 = run.define_metric("glob")
    metric_2 = run.define_metric("val", step_metric=metric_1)
    assert metric_2.step_metric == "glob"

    parsed = parse_records(record_q)
    assert len(parsed.records) == 2

    metric_records = parsed.metric
    assert len(metric_records) == 2

    assert metric_records[0] == pb.MetricRecord(
        name="glob", options=pb.MetricOptions(defined=True)
    )
    assert metric_records[1] == pb.MetricRecord(
        name="val",
        step_metric="glob",
        options=pb.MetricOptions(defined=True, step_sync=True),
    )


def test_metric_hidden(mock_run, parse_records, record_q):
    run = mock_run()
    metric = run.define_metric("glob", hidden=True)
    assert metric.hidden is True

    parsed = parse_records(record_q)
    assert len(parsed.records) == 1
    assert len(parsed.metric) == 1


def test_metric_goal(mock_run, parse_records, record_q):
    run = mock_run()
    metric_1 = run.define_metric(
        "glob",
        goal="maximize",
    )
    assert metric_1.goal == "maximize"

    metric_2 = run.define_metric(
        "glob",
        goal="minimize",
    )
    assert metric_2.goal == "minimize"

    with pytest.raises(wandb.Error):
        run.define_metric(
            "m2",
            goal="nothing",
        )

    parsed = parse_records(record_q)
    assert len(parsed.records) == 2
    assert len(parsed.metric) == 2


def test_metric_step_metric(mock_run, parse_records, record_q):
    run = mock_run()
    metric_1 = run.define_metric(
        "metric",
        step_metric="globalstep",
    )
    assert metric_1.step_metric == "globalstep"

    metric_2 = run.define_metric(
        "metric",
    )
    assert not metric_2.step_metric

    parsed = parse_records(record_q)
    assert len(parsed.records) == 2
    assert len(parsed.metric) == 2


def test_metric_name(mock_run, parse_records, record_q):
    run = mock_run()
    metirc = run.define_metric(
        "metric",
    )
    assert metirc.name == "metric"

    parsed = parse_records(record_q)
    assert len(parsed.records) == 1
    assert len(parsed.metric) == 1


def test_metric_step_sync(mock_run, parse_records, record_q):
    run = mock_run()
    metric_1 = run.define_metric(
        "metric",
        step_metric="globalstep",
        step_sync=True,
    )
    assert metric_1.step_sync is True

    metric_2 = run.define_metric(
        "metric2",
        step_metric="globalstep",
    )
    # default is true when step_metric is set
    assert metric_2.step_sync

    metric_3 = run.define_metric(
        "metric3",
        step_metric="globalstep",
        step_sync=False,
    )
    assert not metric_3.step_sync

    parsed = parse_records(record_q)
    assert len(parsed.records) == 3
    assert len(parsed.metric) == 3


def test_metric_summary(mock_run, parse_records, record_q):
    run = mock_run()
    metric_1 = run.define_metric(
        "metric",
        summary="min,max",
    )
    assert metric_1.summary == ("min", "max")

    metric_2 = run.define_metric(
        "metric",
    )
    assert not metric_2.summary

    metirc_3 = run.define_metric(
        "metric",
        summary="best",
    )
    assert metirc_3.summary == ("best",)

    metric_4 = run.define_metric(
        "metric",
        summary="mean",
    )
    assert metric_4.summary == ("mean",)

    metric_5 = run.define_metric(
        "metric",
        summary="",
    )
    assert not metric_5.summary

    parsed = parse_records(record_q)
    assert len(parsed.records) == 5
    assert len(parsed.metric) == 5


@pytest.mark.parametrize(
    "args, kwargs",
    [
        (
            "",
            {},
        ),
        (
            "junk",
            {"step_metric": 1},
        ),
        (
            "*invalidprefix",
            {},
        ),
        (
            "metric",
            {"summary": "doesnotexist"},
        ),
    ],
)
def test_metric_invalid_args(args, kwargs, mock_run, parse_records, record_q):
    run = mock_run()
    with pytest.raises(wandb.Error):
        run.define_metric(args, **kwargs)

    parsed = parse_records(record_q)
    assert len(parsed.records) == 0


def test_metric_ignored_extra_args(mock_run, parse_records, record_q, capsys):
    run = mock_run()
    run.define_metric(
        "junk",
        extra=1,
        another=2,
    )
    captured = capsys.readouterr()
    print("GOT out", captured.out)
    print("GOT err", captured.err)
    assert "Unhandled define_metric() arg: extra" in captured.err
    assert "Unhandled define_metric() arg: another" in captured.err

    parsed = parse_records(record_q)
    assert len(parsed.records) == 1
    assert len(parsed.metric) == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"overwrite": True},
    ],
)
def test_metric_twice_or_overwrite(kwargs, mock_run, parse_records, record_q):
    run = mock_run()
    _ = run.define_metric(
        "metric",
        summary="best,max",
        step_metric="thestep",
    )
    _ = run.define_metric(
        "metric",
        summary="min",
        **kwargs,
    )

    parsed = parse_records(record_q)
    assert len(parsed.records) == 2
    assert len(parsed.metric) == 2
    # merging or overwriting happens in handler (internal)
