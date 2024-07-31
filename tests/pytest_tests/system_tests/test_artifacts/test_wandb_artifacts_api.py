import os

import pytest
import wandb
from wandb import Api
import tempfile

from unittest.mock import patch


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


def test_artifact_download_offline_mode(user, wandb_init, monkeypatch):
    project = "test"

    with tempfile.TemporaryDirectory() as tempdir:
        # Create the test file in the temporary directory
        filename = os.path.join(tempdir, "boom.txt")
        with open(filename, "w") as f:
            f.write("testing")

        # Use monkeypatch to set WANDB_MODE 
        monkeypatch.setenv("WANDB_MODE", "offline")

        # Mock the wandb.Api().artifact call to prevent actual network requests 
        with patch("wandb.Api.artifact") as mock_artifact:
            mock_artifact.return_value = wandb.Artifact("test-artifact", "test-type")

            with wandb_init(entity=user, project=project) as run:
                artifact = wandb.Artifact("test-artifact", "test-type")
                artifact.add_file(filename, "test-name")
                run.log_artifact(artifact, aliases=["sequence"])

            with pytest.raises(
                RuntimeError, match="Cannot download artifacts in offline mode."
            ):
                artifact.download()


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


def test_update_aliases_on_artifact(user, wandb_init):
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


def test_delete_collection(wandb_init):
    with wandb_init(project="test") as run:
        art = wandb.Artifact("test-artifact", "test-type")
        with art.new_file("test.txt", "w") as f:
            f.write("testing")
        run.log_artifact(art)
        run.link_artifact(art, "test/test-portfolio")

    project = Api().artifact_type("test-type", project="test")
    portfolio = project.collection("test-portfolio")
    portfolio.delete()

    with pytest.raises(wandb.errors.CommError):
        Api().artifact(
            name=f"{project.entity}/test/test-portfolio:latest",
            type="test-type",
        )

    # The base artifact should still exist.
    Api().artifact(
        name=f"{project.entity}/test/test-artifact:latest",
        type="test-type",
    )

    sequence = project.collection("test-artifact")
    sequence.delete()

    # Until now.
    with pytest.raises(wandb.errors.CommError):
        Api().artifact(
            name=f"{project.entity}/test/test-artifact:latest",
            type="test-type",
        )


def test_log_with_wrong_type_entity_project(wandb_init, logged_artifact):
    # todo: logged_artifact does not work with core
    entity, project = logged_artifact.entity, logged_artifact.project

    draft = logged_artifact.new_draft()
    draft._type = "futz"
    with pytest.raises(ValueError, match="already exists with type 'dataset'"):
        with wandb_init(entity=entity, project=project) as run:
            run.log_artifact(draft)

    draft = logged_artifact.new_draft()
    draft._source_entity = "mistaken"
    with pytest.raises(ValueError, match="owned by entity 'mistaken'"):
        with wandb_init(entity=entity, project=project) as run:
            run.log_artifact(draft)

    draft = logged_artifact.new_draft()
    draft._source_project = "wrong"
    with pytest.raises(ValueError, match="exists in project 'wrong'"):
        with wandb_init(entity=entity, project=project) as run:
            run.log_artifact(draft)


def test_run_log_artifact(wandb_init):
    # Prepare data.
    with wandb_init() as run:
        pass
    run = wandb.Api().run(run.path)

    artifact = wandb.Artifact("my_artifact", type="test")
    artifact.save()
    artifact.wait()

    # Run.
    run.log_artifact(artifact)

    # Assert.
    actual_artifacts = list(run.logged_artifacts())
    assert len(actual_artifacts) == 1
    assert actual_artifacts[0].qualified_name == artifact.qualified_name
