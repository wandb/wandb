"""Tests for the `wandb.apis.PublicApi` module."""


import json
from unittest import mock

import pytest
import wandb
import wandb.apis.public
import wandb.util
from wandb import Api
from wandb.sdk.lib import runid


@pytest.mark.parametrize(
    "path",
    [
        "test/test/test/test",
        "test/test/test/test/test",
    ],
)
def test_from_path_bad_path(user, path):
    with pytest.raises(wandb.Error, match="Invalid path"):
        Api().from_path(path)


def test_from_path_bad_report_path(user):
    with pytest.raises(wandb.Error, match="Invalid report path"):
        Api().from_path("test/test/reports/test-foo")


@pytest.mark.parametrize(
    "path",
    [
        "test/test/reports/XYZ",
        "test/test/reports/Name-foo--XYZ",
    ],
)
def test_from_path_report_type(user, path):
    report = Api().from_path(path)
    assert isinstance(report, wandb.apis.public.BetaReport)


def test_project_to_html(user):
    with mock.patch.dict("os.environ", {"WANDB_ENTITY": "mock_entity"}):
        project = Api().from_path("test")
        assert "mock_entity/test/workspace?jupyter=true" in project.to_html()


@pytest.mark.xfail(reason="TODO: fix this test")
def test_run_from_tensorboard(runner, relay_server, user, api, copy_asset):
    with relay_server() as relay, runner.isolated_filesystem():
        tb_file_name = "events.out.tfevents.1585769947.cvp"
        copy_asset(tb_file_name)
        run_id = runid.generate_id()
        api.sync_tensorboard(".", project="test", run_id=run_id)
        uploaded_files = relay.context.get_run_uploaded_files(run_id)
        assert uploaded_files[0].endswith(tb_file_name)
        assert len(uploaded_files) == 17


@pytest.mark.xfail(
    reason="there is no guarantee that the backend has processed the event"
)
def test_run_metadata(wandb_init):
    project = "test_metadata"
    run = wandb_init(project=project)
    run.finish()

    metadata = Api().run(f"{run.entity}/{project}/{run.id}").metadata
    assert len(metadata)


def test_run_queue(user):
    api = Api()
    queue = api.create_run_queue(
        name="test-queue",
        entity=user,
        access="project",
        type="local-container",
    )
    try:
        assert queue.name == "test-queue"
        assert queue.access == "PROJECT"
        assert queue.type == "local-container"
    finally:
        queue.delete()


def test_from_path(wandb_init, api):
    seed_run = wandb_init()
    seed_run.finish()

    run = api.from_path(f"{seed_run.entity}/{seed_run.project}/{seed_run.id}")
    assert isinstance(run, wandb.apis.public.Run)
    run = api.from_path(f"{seed_run.entity}/{seed_run.project}/runs/{seed_run.id}")
    assert isinstance(run, wandb.apis.public.Run)


def test_display(wandb_init, api):
    seed_run = wandb_init()
    seed_run.finish()

    run = api.from_path(f"{seed_run.entity}/{seed_run.project}/{seed_run.id}")
    assert not run.display()


def test_run_load(base_url, wandb_init, api):
    seed_run = wandb_init()
    seed_run.log(dict(acc=100, loss=0))
    seed_run.finish()

    run = api.run(f"{seed_run.entity}/{seed_run.project}/{seed_run.id}")
    assert run.summary_metrics["acc"] == 100
    assert run.summary_metrics["loss"] == 0
    assert (
        run.url == f"{base_url}/{seed_run.entity}/{seed_run.project}/runs/{seed_run.id}"
    )


def test_run_history(wandb_init, api):
    seed_run = wandb_init()
    seed_run.log(dict(acc=100, loss=0))
    seed_run.finish()

    run = api.run(f"{seed_run.entity}/{seed_run.project}/{seed_run.id}")
    assert run.history(pandas=False)[0]["acc"] == 100
    assert run.history(pandas=False)[0]["loss"] == 0


def test_run_config(wandb_init, api):
    seed_run = wandb_init(config=dict(epochs=10))
    seed_run.finish()

    run = api.run(f"{seed_run.entity}/{seed_run.project}/{seed_run.id}")
    assert run.config == {"epochs": 10}


def test_run_history_keys(wandb_init, api):
    seed_run = wandb_init()
    seed_run.log(dict(acc=100, loss=0))
    seed_run.log(dict(acc=0, loss=1))
    seed_run.finish()

    run = api.run(f"{seed_run.entity}/{seed_run.project}/{seed_run.id}")
    assert run.history(keys=["acc", "loss"], pandas=False) == [
        {"_step": 0, "loss": 0, "acc": 100},
        {"_step": 1, "loss": 1, "acc": 0},
    ]


def test_run_history_keys_bad_arg(wandb_init, api, capsys):
    seed_run = wandb_init()
    seed_run.finish()

    run = api.run(f"{seed_run.entity}/{seed_run.project}/{seed_run.id}")

    run.history(keys="acc", pandas=False)
    captured = capsys.readouterr()
    assert "wandb: ERROR keys must be specified in a list\n" in captured.err

    run.history(keys=[["acc"]], pandas=False)
    captured = capsys.readouterr()
    assert "wandb: ERROR keys argument must be a list of strings\n" in captured.err

    run.scan_history(keys="acc")
    captured = capsys.readouterr()
    assert "wandb: ERROR keys must be specified in a list\n" in captured.err

    run.scan_history(keys=[["acc"]])
    captured = capsys.readouterr()
    assert "wandb: ERROR keys argument must be a list of strings\n" in captured.err


def test_run_summary(wandb_init, relay_server):
    seed_run = wandb_init()
    seed_run.finish()

    with relay_server() as relay:
        run = Api().run(f"{seed_run.entity}/{seed_run.project}/{seed_run.id}")
        run.summary.update({"cool": 1000})

        result = json.loads(relay.context.get_run(run.storage_id)["summaryMetrics"])
        assert result["cool"] == 1000


def test_run_create(user, relay_server):
    with relay_server() as relay:
        run = Api().create_run(project="test")
        result = relay.context.get_run(run.id)
        assert result["entity"] == user
        assert result["project"]["name"] == "test"
        assert result["name"] == run.id


def test_run_update(wandb_init, relay_server):
    seed_run = wandb_init()
    seed_run.finish()

    with relay_server() as relay:
        run = Api().run(f"{seed_run.entity}/{seed_run.project}/{seed_run.id}")
        run.tags.append("test")
        run.config["foo"] = "bar"
        run.update()

        result = relay.context.get_run(run.id)
        assert result["tags"] == ["test"]
        assert result["config"]["foo"]["value"] == "bar"
        assert result["entity"] == seed_run.entity
