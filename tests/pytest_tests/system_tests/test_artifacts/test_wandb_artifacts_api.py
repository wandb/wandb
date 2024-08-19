import os
import re

import pytest
import wandb
from wandb import Api
from wandb.errors import CommError


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


def test_artifact_download_offline_mode(
    user, wandb_init, monkeypatch, tmp_path, mocker
):
    project = "test"

    # Create the test file in the temporary directory
    file_path = tmp_path / "boom.txt"
    file_path.write_text("testing")

    # Mock the wandb.Api().artifact call
    mock_api_artifact = mocker.patch("wandb.Api.artifact")
    mock_api_artifact.return_value = wandb.Artifact("test-artifact", "test-type")

    with wandb_init(entity=user, project=project) as run:
        artifact = wandb.Artifact("test-artifact", "test-type")
        artifact.add_file(str(file_path), "test-name")  # Convert Path to string
        run.log_artifact(artifact, aliases=["sequence"])
        artifact.wait()

    # Use monkeypatch to set WANDB_MODE after creating the artifact
    monkeypatch.setenv("WANDB_MODE", "offline")

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


@pytest.mark.parametrize(
    "orig_tags",
    (
        ["orig-tag", "other-tag"],
        ["orig tag", "other-tag"],
        ["orig-TAG 1", "other-tag"],
    ),
)
@pytest.mark.parametrize("edit_tags_inplace", (True, False))
def test_save_tags_after_logging_artifact(
    tmp_path, user, wandb_init, api, orig_tags, edit_tags_inplace
):
    project = "test"
    artifact_name = "test-artifact"
    artifact_type = "test-type"
    artifact_fullname = f"{user}/{project}/{artifact_name}:v0"

    artifact_filepath = tmp_path / "boom.txt"
    artifact_filepath.write_text("testing")

    tags_to_delete = ["other-tag"]  # Tags to delete later on
    tags_to_add = ["added-tag"]  # Tags to add later on

    with wandb_init(entity=user, project=project) as run:
        artifact = wandb.Artifact(name=artifact_name, type=artifact_type)
        artifact.add_file(str(artifact_filepath), "test-name")

        # Assign tags when logging
        run.log_artifact(artifact, tags=orig_tags)
        artifact.wait()

    # Add new tags after and outside the run
    fetched_artifact = api.artifact(name=artifact_fullname, type=artifact_type)

    # Order-agnostic comparison that checks uniqueness (since tagCategories are currently unused/ignored)
    assert sorted(fetched_artifact.tags) == sorted(set(orig_tags))

    if edit_tags_inplace:
        # Partial check that expected behavior is (reasonably) resilient to in-place mutations
        # of the list-type `.tags` attribute -- and not just reassignment.
        #
        # The latter is preferable in python (generally) as well as here (it actually calls the property setter),
        # but it's reasonable to expect some users might prefer or need to rely instead on:
        # - `artifact.tags.extend`
        # - `artiafct.tags.append`
        # - `artifact.tags += ["new-tag"]`
        # - etc.
        for added_tag in tags_to_add:
            fetched_artifact.tags.append(added_tag)
        for deleted_tag in tags_to_delete:
            fetched_artifact.tags.remove(deleted_tag)
    else:
        old_tags = fetched_artifact.tags
        fetched_artifact.tags = [
            tag for tag in (old_tags + tags_to_add) if (tag not in tags_to_delete)
        ]

    fetched_artifact.save()

    # fetch the final artifact and verify its tags
    final_tags = api.artifact(name=artifact_fullname, type=artifact_type).tags

    # Order-agnostic comparison that checks uniqueness (since tagCategories are currently unused/ignored)
    assert sorted(final_tags) == sorted({*orig_tags, *tags_to_add} - {*tags_to_delete})


INVALID_TAGS = (
    "!invalid-tag:with-punctuation",
    "",
    " ",
    "trailing space ",
    " leading space",
)


@pytest.mark.parametrize(
    # Note: Consider `hypothesis` for testing/fuzzing instead if we can reduce setup + wandb.init() time
    "tags_to_add",
    (
        # Given a single invalid tag
        *([bad] for bad in INVALID_TAGS),
        # Given an invalid + valid tag
        *([bad, "good-tag"] for bad in INVALID_TAGS),
        # Given pairs of invalid tags
        *([bad1, bad2] for bad1, bad2 in zip(INVALID_TAGS[:-1], INVALID_TAGS[1:])),
    ),
)
def test_save_invalid_tags_after_logging_artifact(
    tmp_path, user, wandb_init, api, tags_to_add
):
    project = "test"
    artifact_name = "test-artifact"
    artifact_type = "test-type"
    artifact_fullname = f"{user}/{project}/{artifact_name}:v0"

    artifact_filepath = tmp_path / "boom.txt"
    artifact_filepath.write_text("testing")

    orig_tags = ["orig-tag", "other-tag"]  # Initial tags on the logged artifact

    with wandb_init(entity=user, project=project) as run:
        artifact = wandb.Artifact(name=artifact_name, type=artifact_type)
        artifact.add_file(str(artifact_filepath), "test-name")

        # Assign tags when logging
        run.log_artifact(artifact, tags=orig_tags)
        artifact.wait()

    # Add new tags after and outside the run
    fetched_artifact = api.artifact(name=artifact_fullname, type=artifact_type)

    # Order-agnostic comparison that checks uniqueness (since tagCategories are currently unused/ignored)
    assert sorted(fetched_artifact.tags) == sorted(set(orig_tags))

    with pytest.raises(
        (ValueError, CommError),
        match=re.compile(r"Invalid tag", re.IGNORECASE),
    ):
        fetched_artifact.tags.extend(tags_to_add)
        fetched_artifact.save()

    # tags should remain unchanged
    final_tags = api.artifact(name=artifact_fullname, type=artifact_type).tags

    # Order-agnostic comparison that checks uniqueness (since tagCategories are currently unused/ignored)
    assert sorted(final_tags) == sorted(set(orig_tags))


@pytest.mark.parametrize(
    "invalid_tags",
    (
        # Given a single invalid tag
        *([bad] for bad in INVALID_TAGS),
        # Given an invalid + valid tag
        *([bad, "good-tag"] for bad in INVALID_TAGS),
        # Given pairs of invalid tags
        *([bad1, bad2] for bad1, bad2 in zip(INVALID_TAGS[:-1], INVALID_TAGS[1:])),
    ),
)
def test_log_artifact_with_invalid_tags(tmp_path, user, wandb_init, api, invalid_tags):
    project = "test"
    artifact_name = "test-artifact"
    artifact_type = "test-type"

    artifact_filepath = tmp_path / "boom.txt"
    artifact_filepath.write_text("testing")

    with wandb_init(entity=user, project=project) as run:
        artifact = wandb.Artifact(name=artifact_name, type=artifact_type)
        artifact.add_file(str(artifact_filepath), "test-name")

        # Logging an artifact with invalid tags should fail
        with pytest.raises(ValueError, match=re.compile(r"Invalid tag", re.IGNORECASE)):
            run.log_artifact(artifact, tags=invalid_tags)


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
