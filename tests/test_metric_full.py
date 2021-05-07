"""
metric full tests.
"""

import math
import numpy as np
import six
import wandb

from wandb.proto import wandb_telemetry_pb2 as tpb


def test_metric_default(live_mock_server, test_settings, parse_ctx):
    run = wandb.init(settings=test_settings)
    run.log(dict(mystep=1, val=2))
    run.log(dict(mystep=2, val=8))
    run.log(dict(mystep=3, val=3))
    run.log(dict(val2=4))
    run.log(dict(val2=1))
    run.finish()

    ctx_util = parse_ctx(live_mock_server.get_ctx())

    # by default we use last value
    summary = ctx_util.summary
    assert six.viewitems(dict(val=3, val2=1)) <= six.viewitems(summary)


def test_metric_copy(live_mock_server, test_settings, parse_ctx):
    run = wandb.init(settings=test_settings)
    run.define_metric("*", summary="copy")
    run.log(dict(mystep=1, val=2))
    run.log(dict(mystep=2, val=8))
    run.log(dict(mystep=3, val=3))
    run.log(dict(val2=4))
    run.log(dict(val2=1))
    run.finish()

    ctx_util = parse_ctx(live_mock_server.get_ctx())

    summary = ctx_util.summary
    assert six.viewitems(dict(val=3, val2=1, mystep=3)) <= six.viewitems(summary)


def test_metric_glob_none(live_mock_server, test_settings, parse_ctx):
    run = wandb.init(settings=test_settings)
    run.define_metric("*", summary="copy")
    run.define_metric("val", summary="none")
    run.log(dict(mystep=1, val=2))
    run.log(dict(mystep=2, val=8))
    run.log(dict(mystep=3, val=3))
    run.log(dict(val2=4))
    run.log(dict(val2=1))
    run.finish()

    ctx_util = parse_ctx(live_mock_server.get_ctx())

    summary = ctx_util.summary
    assert six.viewitems(dict(val2=1, mystep=3)) <= six.viewitems(summary)
    assert "val" not in summary


def test_metric_glob(live_mock_server, test_settings, parse_ctx):
    run = wandb.init(settings=test_settings)
    run.define_metric("*", step_metric="mystep")
    run.log(dict(mystep=1, val=2))

    run.finish()
    ctx_util = parse_ctx(live_mock_server.get_ctx())
    summary = ctx_util.summary

    assert six.viewitems(dict(val=2)) <= six.viewitems(summary)


def test_metric_nosummary(live_mock_server, test_settings, parse_ctx):
    run = wandb.init(settings=test_settings)
    run.define_metric("val")
    run.log(dict(val2=4))
    run.log(dict(val2=1))
    run.finish()
    ctx_util = parse_ctx(live_mock_server.get_ctx())
    summary = ctx_util.summary
    assert six.viewitems(dict(val2=1)) <= six.viewitems(summary)


def test_metric_none(live_mock_server, test_settings, parse_ctx):
    run = wandb.init(settings=test_settings)
    run.define_metric("val2", summary="none")
    run.log(dict(val2=4))
    run.log(dict(val2=1))
    run.finish()
    ctx_util = parse_ctx(live_mock_server.get_ctx())
    summary = ctx_util.summary
    assert "val2" not in summary


def test_metric_sum_none(live_mock_server, test_settings, parse_ctx):
    run = wandb.init(settings=test_settings)
    run.define_metric("val")
    run.log(dict(mystep=1, val=2))
    run.log(dict(mystep=1, val=8))
    run.log(dict(mystep=1, val=3))
    run.log(dict(val2=4))
    run.log(dict(val2=1))
    run.finish()
    ctx_util = parse_ctx(live_mock_server.get_ctx())
    summary = ctx_util.summary
    # if we set a metric, last is NOT disabled
    assert six.viewitems(dict(val=3, val2=1)) <= six.viewitems(summary)


def test_metric_max(live_mock_server, test_settings, parse_ctx):
    run = wandb.init(settings=test_settings)
    run.define_metric("val", summary="max")
    run.log(dict(mystep=1, val=2))
    run.log(dict(mystep=1, val=8))
    run.log(dict(mystep=1, val=3))
    assert run.summary.get("val") and run.summary["val"].get("max") == 8
    run.finish()
    ctx_util = parse_ctx(live_mock_server.get_ctx())
    summary = ctx_util.summary
    assert summary.get("val", {}).get("max") == 8


def test_metric_min(live_mock_server, test_settings, parse_ctx):
    run = wandb.init(settings=test_settings)
    run.define_metric("val", summary="min")
    run.log(dict(mystep=1, val=2))
    run.log(dict(mystep=1, val=8))
    run.log(dict(mystep=1, val=3))
    assert run.summary.get("val") and run.summary["val"].get("min") == 2
    run.finish()
    ctx_util = parse_ctx(live_mock_server.get_ctx())
    summary = ctx_util.summary
    assert summary.get("val", {}).get("min") == 2


def test_metric_last(live_mock_server, test_settings, parse_ctx):
    run = wandb.init(settings=test_settings)
    run.define_metric("val", summary="last")
    run.log(dict(mystep=1, val=2))
    run.log(dict(mystep=1, val=8))
    run.log(dict(mystep=1, val=3))
    assert run.summary.get("val") and run.summary["val"].get("last") == 3
    run.finish()
    ctx_util = parse_ctx(live_mock_server.get_ctx())
    summary = ctx_util.summary
    assert summary.get("val", {}).get("last") == 3


def _gen_metric_sync_step(run):
    run.log(dict(val=2, val2=5, mystep=1))
    run.log(dict(mystep=3))
    run.log(dict(val=8))
    run.log(dict(val2=8))
    run.log(dict(val=3, mystep=5))
    run.finish()


def test_metric_no_sync_step(live_mock_server, test_settings, parse_ctx):
    run = wandb.init(settings=test_settings)
    run.define_metric("val", summary="min", step_metric="mystep", step_sync=False)
    _gen_metric_sync_step(run)
    ctx_util = parse_ctx(live_mock_server.get_ctx())
    summary = ctx_util.summary
    history = ctx_util.history
    metrics = ctx_util.metrics
    assert summary.get("val", {}).get("min") == 2
    history_val = [(h.get("val"), h.get("mystep")) for h in history if "val" in h]
    assert history_val == [(2, 1), (8, None), (3, 5)]

    assert metrics and len(metrics) == 2


def test_metric_sync_step(live_mock_server, test_settings, parse_ctx):
    run = wandb.init(settings=test_settings)
    run.define_metric("val", summary="min", step_metric="mystep", step_sync=True)
    _gen_metric_sync_step(run)
    ctx_util = parse_ctx(live_mock_server.get_ctx())
    summary = ctx_util.summary
    history = ctx_util.history
    telemetry = ctx_util.telemetry
    metrics = ctx_util.metrics
    assert summary.get("val", {}).get("min") == 2
    history_val = [(h.get("val"), h.get("mystep")) for h in history if "val" in h]
    assert history_val == [(2, 1), (8, 3), (3, 5)]
    assert not any([item[1] is None for item in history_val])

    # metric in telemetry options
    assert telemetry and 7 in telemetry.get("3", [])
    assert metrics and len(metrics) == 2


def test_metric_mult(live_mock_server, test_settings, parse_ctx):
    run = wandb.init(settings=test_settings)
    run.define_metric("mystep", hide=True)
    run.define_metric("*", step_metric="mystep")
    _gen_metric_sync_step(run)
    ctx_util = parse_ctx(live_mock_server.get_ctx())
    metrics = ctx_util.metrics
    assert metrics and len(metrics) == 3


def test_metric_goal(live_mock_server, test_settings, parse_ctx):
    run = wandb.init(settings=test_settings)
    run.define_metric("mystep", hide=True)
    run.define_metric("*", step_metric="mystep", goal="maximize")
    _gen_metric_sync_step(run)
    ctx_util = parse_ctx(live_mock_server.get_ctx())
    metrics = ctx_util.metrics
    assert metrics and len(metrics) == 3


def test_metric_nan_mean(live_mock_server, test_settings, parse_ctx):
    run = wandb.init(settings=test_settings)
    run.define_metric("val", summary="mean")
    run.log(dict(mystep=1, val=2))
    run.log(dict(mystep=1, val=float("nan")))
    run.log(dict(mystep=1, val=4))
    run.finish()
    ctx_util = parse_ctx(live_mock_server.get_ctx())
    summary = ctx_util.summary
    assert summary.get("val", {}).get("mean") == 3


def test_metric_nan_min_norm(live_mock_server, test_settings, parse_ctx):
    run = wandb.init(settings=test_settings)
    run.define_metric("val", summary="min")
    run.log(dict(mystep=1, val=float("nan")))
    run.finish()
    ctx_util = parse_ctx(live_mock_server.get_ctx())
    summary = ctx_util.summary
    assert "min" not in summary.get("val", {})


def test_metric_nan_min_more(live_mock_server, test_settings, parse_ctx):
    run = wandb.init(settings=test_settings)
    run.define_metric("val", summary="min")
    run.log(dict(mystep=1, val=float("nan")))
    run.log(dict(mystep=1, val=4))
    run.finish()
    ctx_util = parse_ctx(live_mock_server.get_ctx())
    summary = ctx_util.summary
    assert summary.get("val", {}).get("min") == 4


def test_metric_nested_default(live_mock_server, test_settings, parse_ctx):
    run = wandb.init(settings=test_settings)
    run.log(dict(this=dict(that=3)))
    run.log(dict(this=dict(that=2)))
    run.log(dict(this=dict(that=4)))
    run.finish()
    ctx_util = parse_ctx(live_mock_server.get_ctx())
    summary = ctx_util.summary
    assert summary.get("this", {}).get("that", {}) == 4


def test_metric_nested_copy(live_mock_server, test_settings, parse_ctx):
    run = wandb.init(settings=test_settings)
    run.define_metric("this.that", summary="copy")
    run.log(dict(this=dict(that=3)))
    run.log(dict(this=dict(that=2)))
    run.log(dict(this=dict(that=4)))
    run.finish()
    ctx_util = parse_ctx(live_mock_server.get_ctx())
    summary = ctx_util.summary
    assert summary.get("this", {}).get("that", {}) == 4


def test_metric_nested_min(live_mock_server, test_settings, parse_ctx):
    run = wandb.init(settings=test_settings)
    run.define_metric("this.that", summary="min")
    run.log(dict(this=dict(that=3)))
    run.log(dict(this=dict(that=2)))
    run.log(dict(this=dict(that=4)))
    run.finish()
    ctx_util = parse_ctx(live_mock_server.get_ctx())
    summary = ctx_util.summary
    assert summary.get("this", {}).get("that", {}).get("min") == 2


def test_metric_nested_mult(live_mock_server, test_settings, parse_ctx):
    run = wandb.init(settings=test_settings)
    run.define_metric("this.that", summary="min,max")
    run.log(dict(this=dict(that=3)))
    run.log(dict(this=dict(that=2)))
    run.log(dict(this=dict(that=4)))
    run.finish()
    ctx_util = parse_ctx(live_mock_server.get_ctx())
    summary = ctx_util.summary
    metrics = ctx_util.metrics
    assert summary.get("this", {}).get("that", {}).get("min") == 2
    assert summary.get("this", {}).get("that", {}).get("max") == 4
    assert len(metrics) == 1
    assert metrics[0] == {"1": "this.that", "7": [1, 2], "6": [3]}


def test_metric_dotted(live_mock_server, test_settings, parse_ctx):
    """escaped dotted define metric matches dotted metrics."""
    run = wandb.init(settings=test_settings)
    run.define_metric("this\\.that", summary="min")
    run.log({"this.that": 3})
    run.log({"this.that": 2})
    run.log({"this.that": 4})
    run.finish()
    ctx_util = parse_ctx(live_mock_server.get_ctx())
    summary = ctx_util.summary
    metrics = ctx_util.metrics
    assert summary.get("this.that", {}).get("min") == 2
    assert len(metrics) == 1
    assert metrics[0] == {"1": "this\\.that", "7": [1], "6": [3]}


def test_metric_nested_glob(live_mock_server, test_settings, parse_ctx):
    run = wandb.init(settings=test_settings)
    run.define_metric("*", summary="min,max")
    run.log(dict(this=dict(that=3)))
    run.log(dict(this=dict(that=2)))
    run.log(dict(this=dict(that=4)))
    run.finish()
    ctx_util = parse_ctx(live_mock_server.get_ctx())
    summary = ctx_util.summary
    metrics = ctx_util.metrics
    assert summary.get("this", {}).get("that", {}).get("min") == 2
    assert summary.get("this", {}).get("that", {}).get("max") == 4
    assert len(metrics) == 1
    assert metrics[0] == {"1": "this.that", "7": [1, 2]}


def test_metric_debouncing(live_mock_server, test_settings):
    # addresses WB-5424
    run = wandb.init(settings=test_settings)
    run.define_metric("*", summary="min,max")

    # test many defined metrics logged at once
    log_arg = {str(i): i for i in range(100)}
    run.log(log_arg)

    # and serially
    for i in range(100, 200):
        run.log({str(i): i})

    run.finish()

    ctx = live_mock_server.get_ctx()

    # without debouncing, the number of config updates should be ~200, one for each defined metric.
    # with debouncing, the number should be << 12 (the minimum number of debounce loops to exceed the
    # 60s test timeout at a 5s debounce interval)
    assert ctx["upsert_bucket_count"] <= 12
