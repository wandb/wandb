from __future__ import annotations

import os
import re

import pytest
import wandb
from wandb import Api
from wandb.errors import CommError
from wandb.sdk.artifacts.artifact import Artifact
from wandb.sdk.lib.hashutil import md5_file_hex


def test_fetching_artifact_files(user):
    project = "test"

    with wandb.init(entity=user, project=project) as run:
        artifact = wandb.Artifact("test-artifact", "test-type")
        with open("boom.txt", "w") as f:
            f.write("testing")
        artifact.add_file("boom.txt", "test-name")
        run.log_artifact(artifact, aliases=["sequence"])

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


def test_save_aliases_after_logging_artifact(user):
    project = "test"
    run = wandb.init(entity=user, project=project)
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


@pytest.fixture
def server_supports_artifact_tags() -> bool:
    """Identifies if we're testing against an older server version that doesn't support artifact tags (e.g. in CI)."""
    from wandb.sdk.internal import internal_api

    return "tags" in internal_api.Api().server_artifact_introspection()


def test_save_artifact_with_tags_repeated(
    user, server_supports_artifact_tags, logged_artifact
):
    tags1 = ["tag1", "tag2"]
    tags2 = ["tag3", "tag4"]

    artifact = logged_artifact

    artifact.tags = tags1
    artifact.save()

    if server_supports_artifact_tags:
        assert set(artifact.tags) == set(tags1)
    else:
        assert artifact.tags == []

    artifact.tags = artifact.tags + tags2
    artifact.save()

    if server_supports_artifact_tags:
        assert set(artifact.tags) == set(tags1 + tags2)
    else:
        assert artifact.tags == []


@pytest.mark.parametrize(
    "orig_tags",
    (
        ["orig-tag", "other-tag"],
        ["orig-TAG 1", "other-tag"],
    ),
)
@pytest.mark.parametrize("edit_tags_inplace", (True, False))
def test_save_tags_after_logging_artifact(
    tmp_path,
    user,
    api,
    orig_tags,
    edit_tags_inplace,
    server_supports_artifact_tags,
):
    project = "test"
    artifact_name = "test-artifact"
    artifact_type = "test-type"
    artifact_fullname = f"{user}/{project}/{artifact_name}:v0"

    artifact_filepath = tmp_path / "boom.txt"
    artifact_filepath.write_text("testing")

    tags_to_delete = ["other-tag"]  # Tags to delete later on
    tags_to_add = ["added-tag"]  # Tags to add later on

    with wandb.init(entity=user, project=project) as run:
        artifact = wandb.Artifact(name=artifact_name, type=artifact_type)
        artifact.add_file(str(artifact_filepath), "test-name")

        # Assign tags when logging
        run.log_artifact(artifact, tags=orig_tags)
        artifact.wait()

    # Add new tags after and outside the run
    fetched_artifact = api.artifact(name=artifact_fullname, type=artifact_type)

    if server_supports_artifact_tags:
        # Order-agnostic comparison that checks uniqueness (since tagCategories are currently unused/ignored)
        assert sorted(fetched_artifact.tags) == sorted(set(orig_tags))
    else:
        assert fetched_artifact.tags == []

    curr_tags = fetched_artifact.tags
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
        fetched_artifact.tags[:] = [
            tag for tag in (curr_tags + tags_to_add) if tag not in tags_to_delete
        ]
    else:
        fetched_artifact.tags = [
            tag for tag in (curr_tags + tags_to_add) if tag not in tags_to_delete
        ]

    fetched_artifact.save()

    # fetch the final artifact and verify its tags
    final_tags = api.artifact(name=artifact_fullname, type=artifact_type).tags

    if server_supports_artifact_tags:
        # Order-agnostic comparison that checks uniqueness (since tagCategories are currently unused/ignored)
        assert sorted(final_tags) == sorted(
            {*orig_tags, *tags_to_add} - {*tags_to_delete}
        )
    else:
        assert final_tags == []


INVALID_TAGS = (
    "!invalid-tag:with-punctuation",
    "",
    " ",
    "trailing space ",
    " leading space",
)

INVALID_TAG_LISTS = (
    # Given a single invalid tag
    *([bad] for bad in INVALID_TAGS),
    # Given an invalid + valid tag
    *([bad, "good-tag"] for bad in INVALID_TAGS),
    # Given pairs of invalid tags
    *([bad1, bad2] for bad1, bad2 in zip(INVALID_TAGS[:-1], INVALID_TAGS[1:])),
)


@pytest.mark.parametrize("tags_to_add", INVALID_TAG_LISTS)
def test_save_invalid_tags_after_logging_artifact(
    tmp_path, user, api, tags_to_add, server_supports_artifact_tags
):
    project = "test"
    artifact_name = "test-artifact"
    artifact_type = "test-type"
    artifact_fullname = f"{user}/{project}/{artifact_name}:v0"

    artifact_filepath = tmp_path / "boom.txt"
    artifact_filepath.write_text("testing")

    orig_tags = ["orig-tag", "other-tag"]  # Initial tags on the logged artifact

    with wandb.init(entity=user, project=project) as run:
        artifact = wandb.Artifact(name=artifact_name, type=artifact_type)
        artifact.add_file(str(artifact_filepath), "test-name")

        # Assign tags when logging
        run.log_artifact(artifact, tags=orig_tags)
        artifact.wait()

    # Add new tags after and outside the run
    fetched_artifact = api.artifact(name=artifact_fullname, type=artifact_type)

    if server_supports_artifact_tags:
        # Order-agnostic comparison that checks uniqueness (since tagCategories are currently unused/ignored)
        assert sorted(fetched_artifact.tags) == sorted(set(orig_tags))
    else:
        assert fetched_artifact.tags == []

    with pytest.raises((ValueError, CommError), match=re.compile(r"Invalid tag", re.I)):
        fetched_artifact.tags.extend(tags_to_add)
        fetched_artifact.save()

    # tags should remain unchanged
    final_tags = api.artifact(name=artifact_fullname, type=artifact_type).tags

    if server_supports_artifact_tags:
        # Order-agnostic comparison that checks uniqueness (since tagCategories are currently unused/ignored)
        assert sorted(final_tags) == sorted(set(orig_tags))
    else:
        assert final_tags == []


@pytest.mark.parametrize("invalid_tags", INVALID_TAG_LISTS)
def test_log_artifact_with_invalid_tags(tmp_path, user, api, invalid_tags):
    project = "test"
    artifact_name = "test-artifact"
    artifact_type = "test-type"

    artifact_filepath = tmp_path / "boom.txt"
    artifact_filepath.write_text("testing")

    with wandb.init(entity=user, project=project) as run:
        artifact = wandb.Artifact(name=artifact_name, type=artifact_type)
        artifact.add_file(str(artifact_filepath), "test-name")

        # Logging an artifact with invalid tags should fail
        with pytest.raises(ValueError, match=re.compile(r"Invalid tag", re.IGNORECASE)):
            run.log_artifact(artifact, tags=invalid_tags)


def test_retrieve_artifacts_by_tags(user, server_supports_artifact_tags):
    project = "test"
    artifact_name = "test-artifact"
    artifact_type = "test-type"

    with wandb.init(entity=user, project=project) as run:
        for i in range(10):
            artifact = wandb.Artifact(name=artifact_name, type=artifact_type)
            with artifact.new_file(f"{i}.txt", "w") as f:
                f.write("testing")
            run.log_artifact(artifact)

    artifact_name = f"{user}/{project}/{artifact_name}"

    for logged_artifact in Api().artifacts(type_name=artifact_type, name=artifact_name):
        version = int(logged_artifact.version.strip("v"))
        if version % 3 == 0:
            logged_artifact.tags.append("fizz")
        if version % 5 == 0:
            logged_artifact.tags.append("buzz")
        logged_artifact.save()

    # Retrieve all artifacts with a given tag.
    artifacts = Api().artifacts(
        type_name=artifact_type, name=artifact_name, tags="fizz"
    )
    retrieved_artifacts = list(artifacts)
    if server_supports_artifact_tags:
        assert len(retrieved_artifacts) == 4  # v0, v3, v6, v9
    else:
        assert len(retrieved_artifacts) == 0

    # Retrieve only the artifacts that match multiple tags.
    artifacts = Api().artifacts(
        type_name=artifact_type, name=artifact_name, tags=["fizz", "buzz"]
    )
    retrieved_artifacts = list(artifacts)
    if server_supports_artifact_tags:
        assert len(retrieved_artifacts) == 1
        assert retrieved_artifacts[0].version == "v0"
    else:
        assert len(retrieved_artifacts) == 0


def test_update_aliases_on_artifact(user):
    project = "test"
    run = wandb.init(entity=user, project=project)
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


def test_artifact_version(user):
    def create_test_artifact(content: str):
        art = wandb.Artifact("test-artifact", "test-type")
        with open("boom.txt", "w") as f:
            f.write(content)
        art.add_file("boom.txt", "test-name")
        return art

    # Create an artifact sequence + portfolio (auto-created if it doesn't exist)
    project = "test"
    run = wandb.init(project=project)

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


def test_delete_collection(user):
    with wandb.init(project="test") as run:
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


def test_log_with_wrong_type_entity_project(user, logged_artifact):
    # todo: logged_artifact does not work with core
    entity, project = logged_artifact.entity, logged_artifact.project

    draft = logged_artifact.new_draft()
    draft._type = "futz"
    with pytest.raises(ValueError, match="already exists with type 'dataset'"):
        with wandb.init(entity=entity, project=project) as run:
            run.log_artifact(draft)

    draft = logged_artifact.new_draft()
    draft._source_entity = "mistaken"
    with pytest.raises(ValueError, match="owned by entity 'mistaken'"):
        with wandb.init(entity=entity, project=project) as run:
            run.log_artifact(draft)

    draft = logged_artifact.new_draft()
    draft._source_project = "wrong"
    with pytest.raises(ValueError, match="exists in project 'wrong'"):
        with wandb.init(entity=entity, project=project) as run:
            run.log_artifact(draft)


def test_log_artifact_with_above_max_metadata_keys(user):
    artifact = wandb.Artifact("my_artifact", type="test")
    for i in range(101):
        artifact.metadata[f"key_{i}"] = f"value_{i}"
    with wandb.init(entity=user, project="test") as run:
        with pytest.raises(ValueError):
            run.log_artifact(artifact)


def test_run_log_artifact(user):
    # Prepare data.
    with wandb.init() as run:
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


def test_artifact_enable_tracking_flag(user, api, mocker):
    """Test that enable_tracking flag is correctly passed through the API chain."""
    entity = user
    project = "test-project"
    artifact_name = "test-artifact"
    artifact_type = "test-type"

    with wandb.init(entity=entity, project=project) as run:
        art = wandb.Artifact(artifact_name, artifact_type)
        with art.new_file("test.txt", "w") as f:
            f.write("testing")
        run.log_artifact(art)

    from_name_spy = mocker.spy(Artifact, "_from_name")
    # Test that api.artifact() calls Artifact._from_name() with enable_tracking=True
    api.artifact(
        name=f"{entity}/{project}/{artifact_name}:v0",
    )
    from_name_spy.assert_called_once_with(
        entity=entity,
        project=project,
        name=f"{artifact_name}:v0",
        client=api.client,
        enable_tracking=True,
    )

    # Test that internal methods, like api.artifact_exists(), call Artifact._from_name() with enable_tracking=False
    from_name_spy.reset_mock()
    api.artifact_exists(
        name=f"{entity}/{project}/{artifact_name}:v0",
    )

    from_name_spy.assert_called_once_with(
        entity=entity,
        project=project,
        name=f"{artifact_name}:v0",
        client=api.client,
        enable_tracking=False,
    )


def test_artifact_history_step(user, api):
    """Test that the correct history step is returned for an artifact."""
    entity = user
    project = "test-project"
    artifact_name = "test-artifact"
    artifact_type = "test-type"

    with wandb.init(entity=entity, project=project) as run:
        for i in range(2):
            art = wandb.Artifact(artifact_name, artifact_type)
            with art.new_file("test.txt", "w") as f:
                f.write(f"testing {i}")
            run.log_artifact(art)
            wandb.log({"metric": 5})

    artifact = api.artifact(
        name=f"{entity}/{project}/{artifact_name}:v0",
    )
    assert artifact.history_step is None

    artifact = api.artifact(
        name=f"{entity}/{project}/{artifact_name}:v1",
    )
    assert artifact.history_step == 0


def test_artifact_multipart_download(user, api):
    """Test download large artifact with multipart download."""
    # Create file with all 1 as 101MB
    file_path = "101mb.bin"
    one_mb = b"\x01" * 1024 * 1024
    with open(file_path, "wb") as f:
        for _ in range(101):
            f.write(one_mb)

    # Hard coded because the file content never changes
    md5_value = "01fedd4cfd8547c8ef960bc041c30523"

    entity = user
    project = "test-project"
    artifact_name = "test-large-artifact"
    artifact_type = "test-type"

    with wandb.init(entity=entity, project=project) as run:
        art = wandb.Artifact(artifact_name, artifact_type)
        art.add_file(file_path)
        run.log_artifact(art)

    # Download artifact
    artifact = api.artifact(
        name=f"{entity}/{project}/{artifact_name}:v0",
    )
    # Force multipart download because the file is too small
    stored_folder = artifact.download(multipart=True, skip_cache=True)
    # Verify checksum
    downloaded_md5 = md5_file_hex(os.path.join(stored_folder, file_path))
    assert downloaded_md5 == md5_value
