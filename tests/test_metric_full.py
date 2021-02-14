"""
metric full tests.
"""

import six
import wandb


def test_metric_none(live_mock_server, test_settings, parse_ctx):
    run = wandb.init()
    run.log(dict(mystep=1, val=2))
    run.log(dict(mystep=2, val=8))
    run.log(dict(mystep=3, val=3))
    run.log(dict(val2=4))
    run.log(dict(val2=1))
    run.finish()

    ctx_util = parse_ctx(live_mock_server.get_ctx())

    # no default axis
    config_wandb = ctx_util.config_wandb
    assert "x_axis" not in config_wandb

    # by default we use last value
    summary = ctx_util.summary
    assert six.viewitems(dict(val=3, val2=1)) <= six.viewitems(summary)


def test_metric_xaxis(live_mock_server, test_settings, parse_ctx):
    run = wandb.init()
    run.define_metric("*", step_metric="mystep")
    run.log(dict(mystep=1, val=2))
    run.finish()
    ctx_util = parse_ctx(live_mock_server.get_ctx())
    config_wandb = ctx_util.config_wandb
    summary = ctx_util.summary

    assert six.viewitems({"x_axis": "mystep"}) <= six.viewitems(config_wandb)
    assert six.viewitems(dict(val=2)) <= six.viewitems(summary)


def test_metric_sum_none(live_mock_server, test_settings, parse_ctx):
    run = wandb.init()
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
    run = wandb.init()
    run.define_metric("val", summary="max")
    run.log(dict(mystep=1, val=2))
    run.log(dict(mystep=1, val=8))
    run.log(dict(mystep=1, val=3))
    run.finish()
    ctx_util = parse_ctx(live_mock_server.get_ctx())
    summary = ctx_util.summary
    assert six.viewitems({"val": 3, "val.max": 8}) <= six.viewitems(summary)


def test_metric_min(live_mock_server, test_settings, parse_ctx):
    run = wandb.init()
    run.define_metric("val", summary="min")
    run.log(dict(mystep=1, val=2))
    run.log(dict(mystep=1, val=8))
    run.log(dict(mystep=1, val=3))
    run.finish()
    ctx_util = parse_ctx(live_mock_server.get_ctx())
    summary = ctx_util.summary
    assert six.viewitems({"val": 3, "val.min": 2}) <= six.viewitems(summary)


def _gen_metric_sync_step(run):
    run.log(dict(val=2, val2=5, mystep=1))
    run.log(dict(mystep=3))
    run.log(dict(val=8))
    run.log(dict(val2=8))
    run.log(dict(val=3, mystep=5))
    run.finish()


def test_metric_no_sync_step(live_mock_server, test_settings, parse_ctx):
    run = wandb.init()
    run.define_metric("val", summary="min", step_metric="mystep")
    _gen_metric_sync_step(run)
    ctx_util = parse_ctx(live_mock_server.get_ctx())
    summary = ctx_util.summary
    history = ctx_util.history
    assert six.viewitems({"val": 3, "val.min": 2}) <= six.viewitems(summary)
    history_val = [(h.get("val"), h.get("mystep")) for h in history if "val" in h]
    assert history_val == [(2, 1), (8, None), (3, 5)]


def test_metric_sync_step(live_mock_server, test_settings, parse_ctx):
    run = wandb.init()
    run.define_metric("val", summary="min", step_metric="mystep", step_sync=True)
    _gen_metric_sync_step(run)
    ctx_util = parse_ctx(live_mock_server.get_ctx())
    summary = ctx_util.summary
    history = ctx_util.history
    assert six.viewitems({"val": 3, "val.min": 2}) <= six.viewitems(summary)
    history_val = [(h.get("val"), h.get("mystep")) for h in history if "val" in h]
    assert history_val == [(2, 1), (8, 3), (3, 5)]
    assert not any([item[1] is None for item in history_val])
