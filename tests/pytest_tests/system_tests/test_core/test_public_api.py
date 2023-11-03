"""Tests for the `wandb.apis.PublicApi` module."""


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
