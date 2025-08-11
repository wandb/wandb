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


@pytest.mark.parametrize(
    "summary,expected",
    [
        ("min", 1),
        ("max", 8),
        ("last", 3),
        ("mean", 4),
        ("first", 1),
    ],
)
def test_metric_summary(summary, expected):
    with wandb.init(mode="offline") as run:
        run.define_metric("val", summary=summary)
        run.log({"val": 1})
        run.log({"val": 8})
        run.log({"val": 3})

        assert run.summary["val"][summary] == expected


@pytest.mark.parametrize(
    "summary,expected",
    [
        ("min", 1),
        ("max", 3),
        ("mean", 2),
        ("first", 1),
    ],
)
def test_metric_summary_string_type(summary, expected):
    with wandb.init(mode="offline") as run:
        run.define_metric("val", summary=summary)
        run.log({"val": 1})
        run.log({"val": "oops a string"})
        run.log({"val": 3})

        assert run.summary["val"][summary] == expected


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
    with wandb.init(
        settings=wandb.Settings(x_server_side_expand_glob_metrics=False),
    ) as run:
        run.define_metric("mystep", hidden=True)
        run.define_metric("*", step_metric="mystep")
        _gen_metric_sync_step(run)

    with wandb_backend_spy.freeze() as snapshot:
        metrics = snapshot.metrics(run_id=run.id)
        assert metrics and len(metrics) == 3


def test_metric_goal(wandb_backend_spy):
    with wandb.init(
        settings=wandb.Settings(x_server_side_expand_glob_metrics=False),
    ) as run:
        run.define_metric("mystep", hidden=True)
        run.define_metric("*", step_metric="mystep", goal="maximize")
        _gen_metric_sync_step(run)

    with wandb_backend_spy.freeze() as snapshot:
        metrics = snapshot.metrics(run_id=run.id)
        assert metrics and len(metrics) == 3


def test_metric_nan_mean(wandb_backend_spy):
    with wandb.init() as run:
        run.define_metric("val", summary="mean")
        run.log(dict(mystep=1, val=2))
        run.log(dict(mystep=1, val=float("nan")))
        run.log(dict(mystep=1, val=4))

    with wandb_backend_spy.freeze() as snapshot:
        summary = snapshot.summary(run_id=run.id)
        assert math.isnan(summary["val"]["mean"])


def test_metric_nan_min_norm(wandb_backend_spy):
    with wandb.init() as run:
        run.define_metric("val", summary="min")
        run.log(dict(mystep=1, val=float("nan")))

    with wandb_backend_spy.freeze() as snapshot:
        summary = snapshot.summary(run_id=run.id)
        assert math.isnan(summary["val"]["min"])


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
        assert metrics[0]["1"] == "this.that"
        assert set(metrics[0]["7"]) == {1, 2}
        assert metrics[0]["6"] == [3]


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


@pytest.mark.parametrize("name", ["m", "*"])
def test_metric_overwrite_false(wandb_backend_spy, name):
    with wandb.init(
        settings=wandb.Settings(x_server_side_expand_glob_metrics=False),
    ) as run:
        run.define_metric(name, summary="min")
        run.define_metric(name, summary="max", overwrite=False)
        run.log({"m": 1})

    with wandb_backend_spy.freeze() as snapshot:
        metrics = snapshot.metrics(run_id=run.id)

        assert metrics[0]["1"] == "m"  # name
        assert set(metrics[0]["7"]) == {1, 2}  # summary; 1=min, 2=max


@pytest.mark.parametrize("name", ["m", "*"])
def test_metric_overwrite_true(wandb_backend_spy, name):
    with wandb.init(
        settings=wandb.Settings(x_server_side_expand_glob_metrics=False),
    ) as run:
        run.define_metric(name, summary="min")
        run.define_metric(name, summary="max", overwrite=True)
        run.log({"m": 1})

    with wandb_backend_spy.freeze() as snapshot:
        metrics = snapshot.metrics(run_id=run.id)

        assert metrics[0]["1"] == "m"  # name
        assert metrics[0]["7"] == [2]  # summary; 2=max


@pytest.mark.parametrize(
    "enable_expand_glob_metrics,server_supports_expand_glob_metrics,expected_metrics",
    [
        (
            True,
            True,
            [
                {"2": "*", "6": [], "7": [1]},
            ],
        ),
        (
            True,
            False,
            [
                {"1": "m", "6": [3], "7": [1]},
            ],
        ),
        (
            False,
            True,
            [
                {"1": "m", "6": [3], "7": [1]},
            ],
        ),
        (
            False,
            False,
            [
                {"1": "m", "6": [3], "7": [1]},
            ],
        ),
    ],
)
def test_metric_expand_glob(
    wandb_backend_spy,
    enable_expand_glob_metrics,
    server_supports_expand_glob_metrics,
    expected_metrics,
):
    """Test that the server expands glob metrics when the server supports it.

    All cases when the server does not support expanding glob metrics or when
    the clientdoes not request it should default to the legacy behavior of
    expanding glob metrics on the client side.
    """
    # stub the server features query to return that the server supports expanding
    # glob metrics
    gql = wandb_backend_spy.gql
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="ServerFeaturesQuery"),
        gql.once(
            content={
                "data": {
                    "serverInfo": {
                        "features": [
                            {
                                "name": "EXPAND_DEFINED_METRIC_GLOBS",
                                "isEnabled": server_supports_expand_glob_metrics,
                            },
                        ],
                    },
                },
            },
            status=200,
        ),
    )

    with wandb.init(
        settings=wandb.Settings(
            x_server_side_expand_glob_metrics=enable_expand_glob_metrics,
        )
    ) as run:
        run.define_metric("*", summary="min")
        run.log({"m": 1})

    with wandb_backend_spy.freeze() as snapshot:
        metrics = snapshot.metrics(run_id=run.id)
        assert len(metrics) == len(expected_metrics)
        assert metrics == expected_metrics
