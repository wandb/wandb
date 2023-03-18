"""Tests for the `wandb.apis.PublicApi` module."""


import os
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


def test_fetching_artifact_files(user, wandb_init):
    project = "test"

    with wandb_init(entity=user, project=project) as run:
        artifact = wandb.Artifact("test-artifact", "test-type")
        with open("boom.txt", "w") as f:
            f.write("testing")
        artifact.add_file("boom.txt", "test-name")
        run.log_artifact(artifact, aliases=["sequence"])

    # run = wandb_init(entity=user, project=project)
    # artifact = wandb.Artifact("test-artifact", "test-type")
    # with open("boom.txt", "w") as f:
    #     f.write("testing")
    # artifact.add_file("boom.txt", "test-name")
    # run.log_artifact(artifact, aliases=["sequence"])
    # artifact.wait()
    # run.finish()

    # fetch artifact and its file successfully
    artifact = Api().artifact(
        name=f"{user}/{project}/test-artifact:v0", type="test-type"
    )
    boom = artifact.files()[0]
    assert boom.name == "test-name"
    artifact_path = artifact.download()
    file_path = os.path.join(artifact_path, boom.name)
    assert os.path.exists(file_path)
    assert open(file_path).read() == "testing"


def test_save_aliases_after_logging_artifact(user, wandb_init):
    project = "test"
    run = wandb_init(entity=user, project=project)
    artifact = wandb.Artifact("test-artifact", "test-type")
    with open("boom.txt", "w") as f:
        f.write("testing")
    artifact.add_file("boom.txt", "test-name")
    run.log_artifact(artifact, aliases=["sequence"])
    artifact.wait()
    artifact.aliases.append("hello")
    artifact.save()
    run.finish()

    # fetch artifact and verify alias exists
    artifact = Api().artifact(
        name=f"{user}/{project}/test-artifact:v0", type="test-type"
    )
    aliases = artifact.aliases
    assert "hello" in aliases


def test_update_aliases_on_artifact(user, relay_server, wandb_init):
    project = "test"
    run = wandb_init(entity=user, project=project)
    artifact = wandb.Artifact("test-artifact", "test-type")
    with open("boom.txt", "w") as f:
        f.write("testing")
    artifact.add_file("boom.txt", "test-name")
    art = run.log_artifact(artifact, aliases=["sequence"])
    run.link_artifact(art, f"{user}/{project}/my-sample-portfolio")
    artifact.wait()
    run.finish()

    # fetch artifact under original parent sequence
    artifact = Api().artifact(
        name=f"{user}/{project}/test-artifact:v0", type="test-type"
    )
    aliases = artifact.aliases
    assert "sequence" in aliases

    # fetch artifact under portfolio
    # and change aliases under portfolio only
    artifact = Api().artifact(
        name=f"{user}/{project}/my-sample-portfolio:v0", type="test-type"
    )
    aliases = artifact.aliases
    assert "sequence" not in aliases
    artifact.aliases = ["portfolio"]
    artifact.aliases.append("boom")
    artifact.save()

    artifact = Api().artifact(
        name=f"{user}/{project}/my-sample-portfolio:v0", type="test-type"
    )
    aliases = artifact.aliases
    assert "portfolio" in aliases
    assert "boom" in aliases
    assert "sequence" not in aliases


def test_artifact_version(wandb_init):
    def create_test_artifact(content: str):
        art = wandb.Artifact("test-artifact", "test-type")
        with open("boom.txt", "w") as f:
            f.write(content)
        art.add_file("boom.txt", "test-name")
        return art

    # Create an artifact sequence + portfolio (auto-created if it doesn't exist)
    project = "test"
    run = wandb_init(project=project)

    art = create_test_artifact("aaaaa")
    run.log_artifact(art, aliases=["a"])
    art.wait()

    art = create_test_artifact("bbbb")
    run.log_artifact(art, aliases=["b"])
    run.link_artifact(art, f"{project}/my-sample-portfolio")
    art.wait()
    run.finish()

    # Pull down from portfolio, verify version is indexed from portfolio not sequence
    artifact = Api().artifact(
        name=f"{project}/my-sample-portfolio:latest", type="test-type"
    )

    assert artifact.version == "v0"
    assert artifact.source_version == "v1"
