"""disabled mode test."""

import os
from unittest import mock

import pytest
import wandb


def test_disabled_noop(user):
    """Make sure that all objects are dummy objects in noop case."""
    with wandb.init(mode="disabled") as run:
        run.log(dict(this=2))


def test_disabled_dir():
    tmp_dir = "/tmp/dir"
    with mock.patch("tempfile.gettempdir", lambda: tmp_dir):
        run = wandb.init(mode="disabled")
        assert run.dir.startswith(tmp_dir)


def test_disabled_summary(user):
    run = wandb.init(mode="disabled")
    run.summary["cat"] = 2
    run.summary["nested"] = dict(level=3)
    assert "cat" in run.summary
    assert run.summary["cat"] == 2
    assert run.summary.cat == 2
    with pytest.raises(KeyError):
        _ = run.summary["dog"]
    assert run.summary["nested"]["level"] == 3


def test_disabled_globals(user):
    # Test wandb.* attributes
    run = wandb.init(config={"foo": {"bar": {"x": "y"}}}, mode="disabled")
    wandb.log({"x": {"y": "z"}})
    wandb.log({"foo": {"bar": {"x": "y"}}})
    assert wandb.run == run
    assert wandb.config == run.config
    assert wandb.summary == run.summary
    assert wandb.config.foo["bar"]["x"] == "y"
    assert wandb.summary["x"].y == "z"
    assert wandb.summary["foo"].bar.x == "y"
    wandb.summary.foo["bar"].update({"a": "b"})
    assert wandb.summary.foo.bar.a == "b"
    run.finish()


def test_bad_url(user):
    run = wandb.init(
        settings=dict(mode="disabled", base_url="http://my-localhost:9000")
    )
    run.log({"acc": 0.9})
    run.finish()


def test_no_dirs(user):
    run = wandb.init(settings={"mode": "disabled"})
    run.log({"acc": 0.9})
    run.finish()
    assert not os.path.isdir("wandb")


def test_access_properties(user):
    run = wandb.init(mode="disabled")
    assert run.dir
    assert run.disabled
    assert run.entity
    assert run.project == "dummy"
    assert run.project_name() == "dummy"
    assert not run.resumed
    assert run.start_time
    assert run.starting_step == 0
    assert run.step == 0
    assert run.url is None
    assert run.get_url() is None
    assert run.sweep_id is None
    assert run.name
    run.tags = ["tag"]
    assert run.tags == ("tag",)
    assert run.offline is False
    assert run.path
    run.notes = "notes"
    assert run.notes == "notes"
    run.name = "name"
    assert run.name == "name"
    assert run.group == ""
    assert run.job_type == ""
    assert run.config_static

    assert run.project_url is None
    assert run.get_project_url() is None
    assert run.sweep_url is None
    assert run.get_sweep_url() is None

    assert run.status() is None

    run.finish()


def test_disabled_no_activity(wandb_backend_spy):
    gql = wandb_backend_spy.gql
    graphql_spy = gql.Capture()
    wandb_backend_spy.stub_gql(gql.any(), graphql_spy)

    with wandb.init(settings={"mode": "disabled"}) as run:
        run.alert("alert")
        run.define_metric("metric")
        run.log_code()
        run.save("/lol")
        run.restore()
        run.mark_preempting()
        run.to_html()
        run.display()
    assert graphql_spy.total_calls == 0


def test_disabled_mode_artifact(wandb_backend_spy):
    gql = wandb_backend_spy.gql
    graphql_spy = gql.Capture()
    wandb_backend_spy.stub_gql(gql.any(), graphql_spy)
    run = wandb.init(settings={"mode": "disabled"})
    art = run.log_artifact(wandb.Artifact("dummy", "dummy")).wait()
    run.link_artifact(art, "dummy")
    run.finish()
    assert graphql_spy.total_calls == 0
