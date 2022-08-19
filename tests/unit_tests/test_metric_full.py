"""
metric full tests.
"""


def test_metric_default(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init()
        run_id = run.id
        run.log(dict(mystep=1, val=2))
        run.log(dict(mystep=2, val=8))
        run.log(dict(mystep=3, val=3))
        run.log(dict(val2=4))
        run.log(dict(val2=1))
        run.finish()

    summary = relay.context.get_run_summary(run_id)

    # by default, we use last value
    assert summary["val"] == 3
    assert summary["val2"] == 1
    assert summary["mystep"] == 3
    assert len(summary) == 3


def test_metric_copy(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init()
        run_id = run.id
        run.define_metric("*", summary="copy")
        run.log(dict(mystep=1, val=2))
        run.log(dict(mystep=2, val=8))
        run.log(dict(mystep=3, val=3))
        run.log(dict(val2=4))
        run.log(dict(val2=1))
        run.finish()

    summary = relay.context.get_run_summary(run_id)

    assert summary["val"] == 3
    assert summary["val2"] == 1
    assert summary["mystep"] == 3
    assert len(summary) == 3


def test_metric_glob_none(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init()
        run_id = run.id
        run.define_metric("*", summary="copy")
        run.define_metric("val", summary="none")
        run.log(dict(mystep=1, val=2))
        run.log(dict(mystep=2, val=8))
        run.log(dict(mystep=3, val=3))
        run.log(dict(val2=4))
        run.log(dict(val2=1))
        run.finish()

    summary = relay.context.get_run_summary(run_id)

    assert summary["val2"] == 1
    assert summary["mystep"] == 3
    assert len(summary) == 2
    assert "val" not in summary


def test_metric_glob(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init()
        run_id = run.id
        run.define_metric("*", step_metric="mystep")
        run.log(dict(mystep=1, val=2))
        run.finish()

    summary = relay.context.get_run_summary(run_id)

    assert summary["val"] == 2
    assert summary["mystep"] == 1
    assert len(summary) == 2


def test_metric_nosummary(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init()
        run_id = run.id
        run.define_metric("val")
        run.log(dict(val2=4))
        run.log(dict(val2=1))
        run.finish()

    summary = relay.context.get_run_summary(run_id)

    assert summary["val2"] == 1
    assert len(summary) == 1


def test_metric_none(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init()
        run_id = run.id
        run.define_metric("val2", summary="none")
        run.log(dict(val2=4))
        run.log(dict(val2=1))
        run.finish()

    summary = relay.context.get_run_summary(run_id)

    assert "val2" not in summary
    assert len(summary) == 0


def test_metric_sum_none(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init()
        run_id = run.id
        run.define_metric("val")
        run.log(dict(mystep=1, val=2))
        run.log(dict(mystep=1, val=8))
        run.log(dict(mystep=1, val=3))
        run.log(dict(val2=4))
        run.log(dict(val2=1))
        run.finish()

    summary = relay.context.get_run_summary(run_id)

    # if we set a metric, last is NOT disabled
    assert summary["val"] == 3
    assert summary["val2"] == 1
    assert summary["mystep"] == 1
    assert len(summary) == 3


def test_metric_max(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init()
        run_id = run.id
        run.define_metric("val", summary="max")
        run.log(dict(mystep=1, val=2))
        run.log(dict(mystep=1, val=8))
        run.log(dict(mystep=1, val=3))
        assert run.summary.get("val") and run.summary["val"].get("max") == 8
        run.finish()

    summary = relay.context.get_run_summary(run_id)

    assert summary["val"] == {"max": 8}
    assert summary["mystep"] == 1
    assert len(summary) == 2


def test_metric_min(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init()
        run_id = run.id
        run.define_metric("val", summary="min")
        run.log(dict(mystep=1, val=2))
        run.log(dict(mystep=1, val=8))
        run.log(dict(mystep=1, val=3))
        assert run.summary.get("val") and run.summary["val"].get("min") == 2
        run.finish()

    summary = relay.context.get_run_summary(run_id)

    assert summary["val"] == {"min": 2}
    assert summary["mystep"] == 1
    assert len(summary) == 2


def test_metric_last(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init()
        run_id = run.id
        run.define_metric("val", summary="last")
        run.log(dict(mystep=1, val=2))
        run.log(dict(mystep=1, val=8))
        run.log(dict(mystep=1, val=3))
        assert run.summary.get("val") and run.summary["val"].get("last") == 3
        run.finish()

    summary = relay.context.get_run_summary(run_id)

    assert summary["val"] == {"last": 3}
    assert summary["mystep"] == 1
    assert len(summary) == 2


def _gen_metric_sync_step(run):
    run.log(dict(val=2, val2=5, mystep=1))
    run.log(dict(mystep=3))
    run.log(dict(val=8))
    run.log(dict(val2=8))
    run.log(dict(val=3, mystep=5))
    run.finish()


def test_metric_no_sync_step(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init()
        run_id = run.id
        run.define_metric("val", summary="min", step_metric="mystep", step_sync=False)
        _gen_metric_sync_step(run)
        run.finish()

    summary = relay.context.get_run_summary(run_id)
    history = relay.context.get_run_history(run_id)
    metrics = relay.context.get_run_metrics(run_id)

    assert summary["val"] == {"min": 2}
    assert summary["val2"] == 8
    assert summary["mystep"] == 5

    history_val = history[history["val"].notnull()][["val", "mystep"]].reset_index(
        drop=True
    )
    assert history_val["val"][0] == 2 and history_val["mystep"][0] == 1
    assert history_val["val"][1] == 8
    assert history_val["val"][2] == 3 and history_val["mystep"][2] == 5

    assert metrics and len(metrics) == 2


def test_metric_sync_step(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init()
        run_id = run.id
        run.define_metric("val", summary="min", step_metric="mystep", step_sync=True)
        _gen_metric_sync_step(run)
        run.finish()

    summary = relay.context.get_run_summary(run_id)
    history = relay.context.get_run_history(run_id)
    metrics = relay.context.get_run_metrics(run_id)
    telemetry = relay.context.get_run_telemetry(run_id)

    assert summary["val"] == {"min": 2}
    assert summary["val2"] == 8
    assert summary["mystep"] == 5

    history_val = history[history["val"].notnull()][["val", "mystep"]].reset_index(
        drop=True
    )
    assert history_val["val"][0] == 2 and history_val["mystep"][0] == 1
    assert history_val["val"][1] == 8 and history_val["mystep"][1] == 3
    assert history_val["val"][2] == 3 and history_val["mystep"][2] == 5
    # Check for nan values
    assert not history_val.isnull().any().sum()

    # metric in telemetry options
    assert telemetry and 7 in telemetry.get("3", [])
    assert metrics and len(metrics) == 2


def test_metric_mult(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init()
        run_id = run.id
        run.define_metric("mystep", hide=True)
        run.define_metric("*", step_metric="mystep")
        _gen_metric_sync_step(run)
        run.finish()

    metrics = relay.context.get_run_metrics(run_id)

    assert metrics and len(metrics) == 3


def test_metric_goal(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init()
        run_id = run.id
        run.define_metric("mystep", hide=True)
        run.define_metric("*", step_metric="mystep", goal="maximize")
        _gen_metric_sync_step(run)
        run.finish()

    metrics = relay.context.get_run_metrics(run_id)

    assert metrics and len(metrics) == 3


def test_metric_nan_mean(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init()
        run_id = run.id
        run.define_metric("val", summary="mean")
        run.log(dict(mystep=1, val=2))
        run.log(dict(mystep=1, val=float("nan")))
        run.log(dict(mystep=1, val=4))
        run.finish()

    summary = relay.context.get_run_summary(run_id)

    assert summary["val"] == {"mean": 3}


def test_metric_nan_min_norm(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init()
        run_id = run.id
        run.define_metric("val", summary="min")
        run.log(dict(mystep=1, val=float("nan")))
        run.finish()

    summary = relay.context.get_run_summary(run_id)

    assert "val" not in summary


def test_metric_nan_min_more(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init()
        run_id = run.id
        run.define_metric("val", summary="min")
        run.log(dict(mystep=1, val=float("nan")))
        run.log(dict(mystep=1, val=4))
        run.finish()

    summary = relay.context.get_run_summary(run_id)

    assert summary["val"] == {"min": 4}


def test_metric_nested_default(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init()
        run_id = run.id
        run.log(dict(this=dict(that=3)))
        run.log(dict(this=dict(that=2)))
        run.log(dict(this=dict(that=4)))
        run.finish()

    summary = relay.context.get_run_summary(run_id)

    assert summary["this"] == {"that": 4}


def test_metric_nested_copy(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init()
        run_id = run.id
        run.define_metric("this.that", summary="copy")
        run.log(dict(this=dict(that=3)))
        run.log(dict(this=dict(that=2)))
        run.log(dict(this=dict(that=4)))
        run.finish()

    summary = relay.context.get_run_summary(run_id)

    assert summary["this"] == {"that": 4}


def test_metric_nested_min(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init()
        run_id = run.id
        run.define_metric("this.that", summary="min")
        run.log(dict(this=dict(that=3)))
        run.log(dict(this=dict(that=2)))
        run.log(dict(this=dict(that=4)))
        run.finish()

    summary = relay.context.get_run_summary(run_id)

    assert summary["this"] == {"that": {"min": 2}}


def test_metric_nested_mult(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init()
        run_id = run.id
        run.define_metric("this.that", summary="min,max")
        run.log(dict(this=dict(that=3)))
        run.log(dict(this=dict(that=2)))
        run.log(dict(this=dict(that=4)))
        run.finish()

    summary = relay.context.get_run_summary(run_id)
    metrics = relay.context.get_run_metrics(run_id)

    assert summary["this"] == {"that": {"min": 2, "max": 4}}
    assert metrics and len(metrics) == 1
    assert metrics[0] == {"1": "this.that", "7": [1, 2], "6": [3]}


def test_metric_dotted(relay_server, wandb_init):
    """escaped dotted define metric matches dotted metrics."""
    with relay_server() as relay:
        run = wandb_init()
        run_id = run.id
        run.define_metric("this\\.that", summary="min")
        run.log({"this.that": 3})
        run.log({"this.that": 2})
        run.log({"this.that": 4})
        run.finish()

    summary = relay.context.get_run_summary(run_id)
    metrics = relay.context.get_run_metrics(run_id)

    assert summary["this.that"] == {"min": 2}
    assert len(metrics) == 1
    assert metrics[0] == {"1": "this\\.that", "7": [1], "6": [3]}


def test_metric_nested_glob(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init()
        run_id = run.id
        run.define_metric("*", summary="min,max")
        run.log(dict(this=dict(that=3)))
        run.log(dict(this=dict(that=2)))
        run.log(dict(this=dict(that=4)))
        run.finish()

    summary = relay.context.get_run_summary(run_id)
    metrics = relay.context.get_run_metrics(run_id)

    assert summary["this"] == {"that": {"min": 2, "max": 4}}
    assert len(metrics) == 1
    assert metrics[0] == {"1": "this.that", "7": [1, 2]}


def test_metric_debouncing(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init()
        run.define_metric("*", summary="min,max")

        # test many defined metrics logged at once
        log_arg = {str(i): i for i in range(100)}
        run.log(log_arg)

        # and serially
        for i in range(100, 200):
            run.log({str(i): i})

        run.finish()

    # without debouncing, the number of config updates should be ~200, one for each defined metric.
    # with debouncing, the number should be << 12 (the minimum number of debounce loops to exceed the
    # 60s test timeout at a 5s debounce interval)
    # assert relay["upsert_bucket_count"] <= 12
    assert (
        1
        <= sum(
            "UpsertBucket" in entry["request"].get("query", "")
            for entry in relay.context.raw_data
        )
        <= 12
    )
