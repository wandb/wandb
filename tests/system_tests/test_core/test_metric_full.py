import math

import pytest
import wandb


@pytest.mark.parametrize("summary_type", [None, "copy"])
def test_default_summary_type_is_last(wandb_backend_spy, summary_type):
    with wandb.init() as run:
        run.define_metric("*", summary=summary_type)
        run.log(dict(mystep=1, val=2))
        run.log(dict(mystep=2, val=8))
        run.log(dict(mystep=3, val=3))
        run.log(dict(val2=4))
        run.log(dict(val2=1))

    with wandb_backend_spy.freeze() as snapshot:
        summary = snapshot.summary(run_id=run.id)
        assert summary["val"] == 3
        assert summary["val2"] == 1
        assert summary["mystep"] == 3


def test_summary_type_none(wandb_backend_spy):
    with wandb.init() as run:
        run.define_metric("*", summary="copy")
        run.define_metric("val", summary="none")
        run.log(dict(val=1, other=1))
        run.log(dict(val=2, other=2))
        run.log(dict(val=3, other=3))

    with wandb_backend_spy.freeze() as snapshot:
        summary = snapshot.summary(run_id=run.id)
        assert summary["other"] == 3
        assert "val" not in summary


def test_metric_glob(wandb_backend_spy):
    with wandb.init() as run:
        run.define_metric("*", step_metric="mystep")
        run.log(dict(mystep=1, val=2))

    with wandb_backend_spy.freeze() as snapshot:
        summary = snapshot.summary(run_id=run.id)
        assert summary["val"] == 2
        assert summary["mystep"] == 1


def test_metric_nosummary(wandb_backend_spy):
    with wandb.init() as run:
        run.define_metric("val")
        run.log(dict(val2=4))
        run.log(dict(val2=1))

    with wandb_backend_spy.freeze() as snapshot:
        summary = snapshot.summary(run_id=run.id)
        assert summary["val2"] == 1


def test_metric_none(wandb_backend_spy):
    with wandb.init() as run:
        run.define_metric("val2", summary="none")
        run.log(dict(val2=4))
        run.log(dict(val2=1))

    with wandb_backend_spy.freeze() as snapshot:
        summary = snapshot.summary(run_id=run.id)
        assert "val2" not in summary


def test_metric_sum_none(wandb_backend_spy):
    with wandb.init() as run:
        run.define_metric("val")
        run.log(dict(mystep=1, val=2))
        run.log(dict(mystep=1, val=8))
        run.log(dict(mystep=1, val=3))
        run.log(dict(val2=4))
        run.log(dict(val2=1))

    with wandb_backend_spy.freeze() as snapshot:
        summary = snapshot.summary(run_id=run.id)
        assert summary["val"] == 3
        assert summary["val2"] == 1
        assert summary["mystep"] == 1


def test_metric_max(wandb_backend_spy):
    with wandb.init() as run:
        run.define_metric("val", summary="max")
        run.log(dict(mystep=1, val=2))
        run.log(dict(mystep=1, val=8))
        run.log(dict(mystep=1, val=3))
        assert run.summary.get("val") and run.summary["val"].get("max") == 8

    with wandb_backend_spy.freeze() as snapshot:
        summary = snapshot.summary(run_id=run.id)
        assert summary["val"] == {"max": 8}
        assert summary["mystep"] == 1


def test_metric_min(wandb_backend_spy):
    with wandb.init() as run:
        run.define_metric("val", summary="min")
        run.log(dict(mystep=1, val=2))
        run.log(dict(mystep=1, val=8))
        run.log(dict(mystep=1, val=3))
        assert run.summary.get("val") and run.summary["val"].get("min") == 2

    with wandb_backend_spy.freeze() as snapshot:
        summary = snapshot.summary(run_id=run.id)
        assert summary["val"] == {"min": 2}
        assert summary["mystep"] == 1


def test_metric_last(wandb_backend_spy):
    with wandb.init() as run:
        run.define_metric("val", summary="last")
        run.log(dict(mystep=1, val=2))
        run.log(dict(mystep=1, val=8))
        run.log(dict(mystep=1, val=3))
        assert run.summary.get("val") and run.summary["val"].get("last") == 3

    with wandb_backend_spy.freeze() as snapshot:
        summary = snapshot.summary(run_id=run.id)
        assert summary["val"] == {"last": 3}
        assert summary["mystep"] == 1


def _gen_metric_sync_step(run):
    run.log(dict(val=2, val2=5, mystep=1))
    run.log(dict(mystep=3))
    run.log(dict(val=8))
    run.log(dict(val2=8))
    run.log(dict(val=3, mystep=5))
    # run.finish()


def test_metric_no_sync_step(wandb_backend_spy):
    with wandb.init() as run:
        run.define_metric(
            "val",
            summary="min",
            step_metric="mystep",
            step_sync=False,
        )
        _gen_metric_sync_step(run)

    with wandb_backend_spy.freeze() as snapshot:
        summary = snapshot.summary(run_id=run.id)
        assert summary["val"] == {"min": 2}
        assert summary["val2"] == 8
        assert summary["mystep"] == 5

        history = snapshot.history(run_id=run.id)
        assert history[0]["val"] == 2 and history[0]["mystep"] == 1
        assert history[1]["mystep"] == 3
        assert history[2]["val"] == 8 and "mystep" not in history[2]
        assert history[4]["val"] == 3 and history[4]["mystep"] == 5

        metrics = snapshot.metrics(run_id=run.id)
        assert metrics and len(metrics) == 2


def test_metric_sync_step(wandb_backend_spy):
    with wandb.init() as run:
        run.define_metric("val", summary="min", step_metric="mystep", step_sync=True)
        _gen_metric_sync_step(run)

    with wandb_backend_spy.freeze() as snapshot:
        summary = snapshot.summary(run_id=run.id)
        assert summary["val"] == {"min": 2}
        assert summary["val2"] == 8
        assert summary["mystep"] == 5

        history = snapshot.history(run_id=run.id)
        assert history[0]["val"] == 2 and history[0]["mystep"] == 1
        assert history[1]["mystep"] == 3
        assert history[2]["val"] == 8 and history[2]["mystep"] == 3
        assert history[4]["val"] == 3 and history[4]["mystep"] == 5

        metrics = snapshot.metrics(run_id=run.id)
        assert metrics and len(metrics) == 2
        telemetry = snapshot.telemetry(run_id=run.id)
        assert telemetry and 7 in telemetry.get("3", [])


def test_metric_mult(wandb_backend_spy):
    with wandb.init() as run:
        run.define_metric("mystep", hidden=True)
        run.define_metric("*", step_metric="mystep")
        _gen_metric_sync_step(run)

    with wandb_backend_spy.freeze() as snapshot:
        metrics = snapshot.metrics(run_id=run.id)
        assert metrics and len(metrics) == 3


def test_metric_goal(wandb_backend_spy):
    with wandb.init() as run:
        run.define_metric("mystep", hidden=True)
        run.define_metric("*", step_metric="mystep", goal="maximize")
        _gen_metric_sync_step(run)

    with wandb_backend_spy.freeze() as snapshot:
        metrics = snapshot.metrics(run_id=run.id)
        assert metrics and len(metrics) == 3


@pytest.mark.wandb_core_only(
    reason="deviates from legacy behavior as nan value should be respected"
)
def test_metric_nan_mean(wandb_backend_spy):
    with wandb.init() as run:
        run.define_metric("val", summary="mean")
        run.log(dict(mystep=1, val=2))
        run.log(dict(mystep=1, val=float("nan")))
        run.log(dict(mystep=1, val=4))

    with wandb_backend_spy.freeze() as snapshot:
        summary = snapshot.summary(run_id=run.id)
        assert math.isnan(summary["val"]["mean"])


@pytest.mark.wandb_core_only(
    reason="deviates from legacy behavior as nan value should be respected"
)
def test_metric_nan_min_norm(wandb_backend_spy):
    with wandb.init() as run:
        run.define_metric("val", summary="min")
        run.log(dict(mystep=1, val=float("nan")))

    with wandb_backend_spy.freeze() as snapshot:
        summary = snapshot.summary(run_id=run.id)
        assert math.isnan(summary["val"]["min"])


@pytest.mark.wandb_core_only(
    reason="deviates from legacy behavior as nan value should be respected"
)
def test_metric_nan_min_more(wandb_backend_spy):
    with wandb.init() as run:
        run.define_metric("val", summary="min")
        run.log(dict(mystep=1, val=float("nan")))
        run.log(dict(mystep=1, val=4))

    with wandb_backend_spy.freeze() as snapshot:
        summary = snapshot.summary(run_id=run.id)
        assert math.isnan(summary["val"]["min"])


def test_metric_nested_default(wandb_backend_spy):
    with wandb.init() as run:
        run.log(dict(this=dict(that=3)))
        run.log(dict(this=dict(that=2)))
        run.log(dict(this=dict(that=4)))

    with wandb_backend_spy.freeze() as snapshot:
        summary = snapshot.summary(run_id=run.id)
        assert summary["this"] == {"that": 4}


def test_metric_nested_copy(wandb_backend_spy):
    with wandb.init() as run:
        run.define_metric("this.that", summary="copy")
        run.log(dict(this=dict(that=3)))
        run.log(dict(this=dict(that=2)))
        run.log(dict(this=dict(that=4)))

    with wandb_backend_spy.freeze() as snapshot:
        summary = snapshot.summary(run_id=run.id)
        assert summary["this"] == {"that": 4}


def test_metric_nested_min(wandb_backend_spy):
    with wandb.init() as run:
        run.define_metric("this.that", summary="min")
        run.log(dict(this=dict(that=3)))
        run.log(dict(this=dict(that=2)))
        run.log(dict(this=dict(that=4)))

    with wandb_backend_spy.freeze() as snapshot:
        summary = snapshot.summary(run_id=run.id)
        assert summary["this"] == {"that": {"min": 2}}


def test_metric_nested_mult(wandb_backend_spy):
    with wandb.init() as run:
        run.define_metric("this.that", summary="min,max")
        run.log(dict(this=dict(that=3)))
        run.log(dict(this=dict(that=2)))
        run.log(dict(this=dict(that=4)))

    with wandb_backend_spy.freeze() as snapshot:
        summary = snapshot.summary(run_id=run.id)
        assert summary["this"] == {"that": {"min": 2, "max": 4}}

        metrics = snapshot.metrics(run_id=run.id)
        assert metrics and len(metrics) == 1
        assert metrics[0] == {"1": "this.that", "7": [1, 2], "6": [3]}


def test_metric_dotted(wandb_backend_spy):
    """Escape dots in metric definitions."""
    with wandb.init() as run:
        run.define_metric("test\\this\\.that", summary="min")
        run.log({"test\\this.that": 3})
        run.log({"test\\this.that": 2})
        run.log({"test\\this.that": 4})

    with wandb_backend_spy.freeze() as snapshot:
        summary = snapshot.summary(run_id=run.id)
        assert summary["test\\this.that"] == {"min": 2}

        metrics = snapshot.metrics(run_id=run.id)
        assert metrics and len(metrics) == 1
        assert metrics[0] == {"1": "test\\this\\.that", "7": [1], "6": [3]}


def test_metric_nested_glob(wandb_backend_spy):
    with wandb.init() as run:
        run.define_metric("*", summary="min,max")
        run.log(dict(this=dict(that=3)))
        run.log(dict(this=dict(that=2)))
        run.log(dict(this=dict(that=4)))

    with wandb_backend_spy.freeze() as snapshot:
        summary = snapshot.summary(run_id=run.id)
        assert summary["this"] == {"that": {"min": 2, "max": 4}}
