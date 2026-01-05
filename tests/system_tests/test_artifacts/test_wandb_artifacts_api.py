from __future__ import annotations

import json
import os
import re
from pathlib import Path

import responses
import wandb
from pytest import mark, raises
from wandb import Api
from wandb.errors import CommError
from wandb.sdk.artifacts._validators import FullArtifactPath
from wandb.sdk.artifacts.artifact import Artifact
from wandb.sdk.lib.hashutil import md5_file_hex


def test_fetching_artifact_files(user: str, api: Api):
    project = "test"

    with wandb.init(entity=user, project=project) as run:
        artifact = wandb.Artifact("test-artifact", "test-type")
        with open("boom.txt", "w") as f:
            f.write("testing")
        artifact.add_file("boom.txt", "test-name")
        run.log_artifact(artifact, aliases=["sequence"])

    # fetch artifact and its file successfully
    artifact = api.artifact(name=f"{user}/{project}/test-artifact:v0", type="test-type")
    boom = artifact.files()[0]
    assert boom.name == "test-name"
    artifact_path = artifact.download()
    file_path = os.path.join(artifact_path, boom.name)
    assert os.path.exists(file_path)
    assert open(file_path).read() == "testing"


def test_save_aliases_after_logging_artifact(user: str, api: Api):
    project = "test"
    with wandb.init(entity=user, project=project) as run:
        artifact = wandb.Artifact("test-artifact", "test-type")
        Path("boom.txt").write_text("testing")

        artifact.add_file("boom.txt", "test-name")
        run.log_artifact(artifact, aliases=["sequence"])
        artifact.wait()
        artifact.aliases.append("hello")
        artifact.save()

    # fetch artifact and verify alias exists
    artifact = api.artifact(name=f"{user}/{project}/test-artifact:v0", type="test-type")
    aliases = artifact.aliases
    assert "hello" in aliases


def test_save_artifact_with_tags_repeated(user: str, logged_artifact: Artifact):
    tags1 = ["tag1", "tag2"]
    tags2 = ["tag3", "tag4"]

    artifact = logged_artifact

    artifact.tags = tags1
    artifact.save()

    assert set(artifact.tags) == set(tags1)

    artifact.tags = artifact.tags + tags2
    artifact.save()

    assert set(artifact.tags) == set(tags1 + tags2)


@mark.parametrize(
    "orig_tags",
    (
        ["orig-tag", "other-tag"],
        ["orig-TAG 1", "other-tag"],
    ),
)
@mark.parametrize("edit_tags_inplace", (True, False))
def test_save_tags_after_logging_artifact(
    tmp_path: Path,
    user: str,
    api: Api,
    orig_tags: list[str],
    edit_tags_inplace: bool,
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

    # Order-agnostic comparison that checks uniqueness (since tagCategories are currently unused/ignored)
    assert sorted(fetched_artifact.tags) == sorted(set(orig_tags))

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

    # Order-agnostic comparison that checks uniqueness (since tagCategories are currently unused/ignored)
    assert sorted(final_tags) == sorted({*orig_tags, *tags_to_add} - {*tags_to_delete})


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


@mark.parametrize("tags_to_add", INVALID_TAG_LISTS)
def test_save_invalid_tags_after_logging_artifact(
    tmp_path: Path,
    user: str,
    api: Api,
    tags_to_add: list[str],
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

    # Order-agnostic comparison that checks uniqueness (since tagCategories are currently unused/ignored)
    assert sorted(fetched_artifact.tags) == sorted(set(orig_tags))

    with raises((ValueError, CommError), match=re.compile(r"Invalid tag", re.I)):
        fetched_artifact.tags.extend(tags_to_add)
        fetched_artifact.save()

    # tags should remain unchanged
    final_tags = api.artifact(name=artifact_fullname, type=artifact_type).tags

    # Order-agnostic comparison that checks uniqueness (since tagCategories are currently unused/ignored)
    assert sorted(final_tags) == sorted(set(orig_tags))


@mark.parametrize("invalid_tags", INVALID_TAG_LISTS)
def test_log_artifact_with_invalid_tags(
    tmp_path: Path,
    user: str,
    invalid_tags: list[str],
):
    project = "test"
    artifact_name = "test-artifact"
    artifact_type = "test-type"

    artifact_filepath = tmp_path / "boom.txt"
    artifact_filepath.write_text("testing")

    with wandb.init(entity=user, project=project) as run:
        artifact = wandb.Artifact(name=artifact_name, type=artifact_type)
        artifact.add_file(str(artifact_filepath), "test-name")

        # Logging an artifact with invalid tags should fail
        with raises(ValueError, match=re.compile(r"Invalid tag", re.IGNORECASE)):
            run.log_artifact(artifact, tags=invalid_tags)


def test_retrieve_artifacts_by_tags(user: str, api: Api):
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

    for logged_artifact in api.artifacts(type_name=artifact_type, name=artifact_name):
        version = int(logged_artifact.version.strip("v"))
        if version % 3 == 0:
            logged_artifact.tags.append("fizz")
        if version % 5 == 0:
            logged_artifact.tags.append("buzz")
        logged_artifact.save()

    # Retrieve all artifacts with a given tag.
    artifacts = api.artifacts(type_name=artifact_type, name=artifact_name, tags="fizz")
    retrieved_artifacts = list(artifacts)
    assert len(retrieved_artifacts) == 4  # v0, v3, v6, v9

    # Retrieve only the artifacts that match multiple tags.
    artifacts = api.artifacts(
        type_name=artifact_type, name=artifact_name, tags=["fizz", "buzz"]
    )
    retrieved_artifacts = list(artifacts)
    assert len(retrieved_artifacts) == 1
    assert retrieved_artifacts[0].version == "v0"


def test_update_aliases_on_artifact(user: str, api: Api):
    project = "test"
    with wandb.init(entity=user, project=project) as run:
        artifact = wandb.Artifact("test-artifact", "test-type")
        Path("boom.txt").write_text("testing")

        artifact.add_file("boom.txt", "test-name")
        art = run.log_artifact(artifact, aliases=["sequence"])
        run.link_artifact(art, f"{user}/{project}/my-sample-portfolio")
        artifact.wait()

    # fetch artifact under original parent sequence
    artifact = api.artifact(name=f"{user}/{project}/test-artifact:v0", type="test-type")
    aliases = artifact.aliases
    assert "sequence" in aliases

    # fetch artifact under portfolio
    # and change aliases under portfolio only
    artifact = api.artifact(
        name=f"{user}/{project}/my-sample-portfolio:v0", type="test-type"
    )
    aliases = artifact.aliases
    assert "sequence" not in aliases
    artifact.aliases = ["portfolio"]
    artifact.aliases.append("boom")
    artifact.save()

    artifact = api.artifact(
        name=f"{user}/{project}/my-sample-portfolio:v0", type="test-type"
    )
    aliases = artifact.aliases
    assert "portfolio" in aliases
    assert "boom" in aliases
    assert "sequence" not in aliases


def test_artifact_version(user: str, api: Api):
    def create_test_artifact(content: str):
        art = wandb.Artifact("test-artifact", "test-type")
        Path("boom.txt").write_text(content)

        art.add_file("boom.txt", "test-name")
        return art

    # Create an artifact sequence + portfolio (auto-created if it doesn't exist)
    project = "test"
    with wandb.init(project=project) as run:
        art = create_test_artifact("aaaaa")
        run.log_artifact(art, aliases=["a"])
        art.wait()

        art = create_test_artifact("bbbb")
        run.log_artifact(art, aliases=["b"])
        run.link_artifact(art, f"{project}/my-sample-portfolio")
        art.wait()

    # Pull down from portfolio, verify version is indexed from portfolio not sequence
    artifact = api.artifact(
        name=f"{project}/my-sample-portfolio:latest", type="test-type"
    )

    assert artifact.version == "v0"
    assert artifact.source_version == "v1"


def test_delete_collection(user: str, api: Api):
    with wandb.init(project="test") as run:
        art = wandb.Artifact("test-artifact", "test-type")
        with art.new_file("test.txt", "w") as f:
            f.write("testing")
        run.log_artifact(art)
        run.link_artifact(art, "test/test-portfolio")

    project = api.artifact_type("test-type", project="test")
    portfolio = project.collection("test-portfolio")
    portfolio.delete()

    with raises(CommError):
        api.artifact(
            name=f"{project.entity}/test/test-portfolio:latest",
            type="test-type",
        )

    # The base artifact should still exist.
    api.artifact(
        name=f"{project.entity}/test/test-artifact:latest",
        type="test-type",
    )

    sequence = project.collection("test-artifact")
    sequence.delete()

    # Until now.
    with raises(CommError):
        api.artifact(
            name=f"{project.entity}/test/test-artifact:latest",
            type="test-type",
        )


def test_log_with_wrong_type_entity_project(
    user: str,
    api: Api,
    logged_artifact: Artifact,
):
    # todo: logged_artifact does not work with core
    entity, project = logged_artifact.entity, logged_artifact.project

    draft = logged_artifact.new_draft()
    draft._type = "futz"
    with raises(ValueError, match="already exists with type 'dataset'"):
        with wandb.init(entity=entity, project=project) as run:
            run.log_artifact(draft)

    draft = logged_artifact.new_draft()
    draft._source_entity = "mistaken"
    with raises(ValueError, match="owned by entity 'mistaken'"):
        with wandb.init(entity=entity, project=project) as run:
            run.log_artifact(draft)

    draft = logged_artifact.new_draft()
    draft._source_project = "wrong"
    with raises(ValueError, match="exists in project 'wrong'"):
        with wandb.init(entity=entity, project=project) as run:
            run.log_artifact(draft)


def test_log_artifact_with_above_max_metadata_keys(user: str):
    artifact = wandb.Artifact("my_artifact", type="test")
    for i in range(101):
        artifact.metadata[f"key_{i}"] = f"value_{i}"
    with wandb.init(entity=user, project="test") as run:
        with raises(ValueError):
            run.log_artifact(artifact)


def test_log_artifact_with_inf_metadata_values(user: str):
    # NOTE: The backend doesn't currently handle JS-compatible `Infinity/-Infinity`, values.
    # At the time of writing, we'll forbid them to avoid surprises, but revisit if we add backend support in the future.
    draft_metadata = {
        "finite_number": 123,
        "pos_inf": float("inf"),
        "neg_inf": float("-inf"),
        "nested": {
            "normal_string": "hello",
            "pos_inf": float("inf"),
            "neg_inf": float("-inf"),
        },
    }

    # In-place update
    with raises(ValueError):
        artifact1 = wandb.Artifact(name="test-artifact-1", type="test")
        artifact1.metadata.update(draft_metadata)
        artifact1.save()

    # Proper attribute assignment
    with raises(ValueError):
        artifact2 = wandb.Artifact(name="test-artifact-2", type="test")
        artifact2.metadata = draft_metadata
        artifact2.save()


def test_log_artifact_with_nan_metadata_values(user: str, api: Api):
    """Check that NaN values are encoded as None (JSON null) values."""
    import numpy as np

    draft_metadata = {
        "finite_number": 123,
        "python_nan": float("nan"),
        "nested": {
            "normal_string": "hello",
            "numpy_nan": np.nan,
        },
    }
    expected_saved_metadata = {
        "finite_number": 123,
        "python_nan": None,
        "nested": {
            "normal_string": "hello",
            "numpy_nan": None,
        },
    }

    # In-place update
    artifact1 = wandb.Artifact(name="test-artifact-1", type="test")
    artifact1.metadata.update(draft_metadata)
    artifact1.save()
    artifact1.wait()
    assert api.artifact(artifact1.qualified_name).metadata == expected_saved_metadata

    # Proper attribute assignment
    artifact2 = wandb.Artifact(name="test-artifact-2", type="test")
    artifact2.metadata = draft_metadata
    artifact2.save()
    artifact2.wait()
    assert api.artifact(artifact2.qualified_name).metadata == expected_saved_metadata


def test_run_log_artifact(user: str, api: Api):
    # Prepare data.
    with wandb.init() as run:
        pass
    run = api.run(run.path)

    artifact = wandb.Artifact("my_artifact", type="test")
    artifact.save()
    artifact.wait()

    # Run.
    run.log_artifact(artifact)

    # Assert.
    actual_artifacts = list(run.logged_artifacts())
    assert len(actual_artifacts) == 1
    assert actual_artifacts[0].qualified_name == artifact.qualified_name


def test_artifact_enable_tracking_flag(user: str, api: Api, mocker):
    """Test that enable_tracking flag is correctly passed through the API chain."""
    entity = user
    project = "test-project"
    artifact_name = "test-artifact"
    artifact_type = "test-type"

    artifact_path_str = f"{entity}/{project}/{artifact_name}:v0"
    artifact_path_obj = FullArtifactPath.from_str(artifact_path_str)

    with wandb.init(entity=entity, project=project) as run:
        art = wandb.Artifact(artifact_name, artifact_type)
        with art.new_file("test.txt", "w") as f:
            f.write("testing")
        run.log_artifact(art)

    from_name_spy = mocker.spy(Artifact, "_from_name")

    # Test that api.artifact() calls Artifact._from_name() with enable_tracking=True
    api.artifact(name=artifact_path_str)

    from_name_spy.assert_called_once_with(
        path=artifact_path_obj,
        client=api.client,
        enable_tracking=True,
    )

    # Test that internal methods, like api.artifact_exists(), call Artifact._from_name() with enable_tracking=False
    from_name_spy.reset_mock()
    api.artifact_exists(name=artifact_path_str)

    from_name_spy.assert_called_once_with(
        path=artifact_path_obj,
        client=api.client,
        enable_tracking=False,
    )


def test_artifact_history_step(user: str, api: Api):
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

    artifact = api.artifact(name=f"{entity}/{project}/{artifact_name}:v0")
    assert artifact.history_step is None

    artifact = api.artifact(name=f"{entity}/{project}/{artifact_name}:v1")
    assert artifact.history_step == 0


def test_artifact_multipart_download(user: str, api: Api):
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
    artifact = api.artifact(name=f"{entity}/{project}/{artifact_name}:v0")
    # Force multipart download because the file is too small
    stored_folder = artifact.download(multipart=True, skip_cache=True)
    # Verify checksum
    downloaded_md5 = md5_file_hex(os.path.join(stored_folder, file_path))
    assert downloaded_md5 == md5_value


def test_artifact_download_http_headers(user, monkeypatch, tmp_path):
    """Test custom HTTP headers are included in full artifact and single entry download requests."""
    custom_headers = {
        "X-Custom-Header": "test-value",
        "X-Another-Header": "another-value",
    }
    monkeypatch.setenv("WANDB_X_EXTRA_HTTP_HEADERS", json.dumps(custom_headers))
    # Reset the singleton so it picks up the new env var.
    wandb.teardown()

    # Create the Api after teardown to ensure it picks up the new settings.
    api = Api()

    entity = user
    project = "test-http-headers-full"
    artifact_name = "test-headers-artifact"

    test_file = tmp_path / "a.txt"
    test_file.write_text("a")
    test_file2 = tmp_path / "b.txt"
    test_file2.write_text("b")

    # Upload artifact files
    with wandb.init(entity=entity, project=project) as run:
        art = wandb.Artifact(artifact_name, "dataset")
        art.add_file(test_file)
        art.add_file(test_file2)
        run.log_artifact(art)
        art.wait()

    art_download_all = api.artifact(f"{entity}/{project}/{artifact_name}:v0")
    # Full artifact download with responses passthrough to capture requests
    # NOTE: PassthroughResponse capture the call while add_passthru() just passes.
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add_passthru(re.compile(".*graphql"))
        rsps.add(responses.PassthroughResponse(responses.GET, re.compile(".*")))

        art_download_all.download(root=tmp_path / "download_all", skip_cache=True)

        storage_requests = [call.request for call in rsps.calls]
        assert len(storage_requests) > 0

        # Expect at least one request for the manifest URL
        assert any("wandb_manifest.json" in req.url for req in storage_requests)

        # Expect all requests to have been populated with the custom headers
        for req in storage_requests:
            assert custom_headers.items() <= req.headers.items()

    # Download single entry using a new artifact
    art_download_entry = api.artifact(f"{entity}/{project}/{artifact_name}:v0")
    # Make sure the artifact is not the cached one with cached manifest
    assert art_download_all != art_download_entry
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add_passthru(re.compile(".*graphql"))
        rsps.add(responses.PassthroughResponse(responses.GET, re.compile(".*")))

        entry = art_download_entry.get_entry("a.txt")
        entry.download(root=tmp_path / "download_entry", skip_cache=True)

        storage_requests = [call.request for call in rsps.calls]
        assert len(storage_requests) > 0

        # Expect all requests to have been populated with the custom headers
        for req in storage_requests:
            assert custom_headers.items() <= req.headers.items()
