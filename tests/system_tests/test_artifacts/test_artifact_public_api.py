from __future__ import annotations

import os
import platform
import random
import string
from contextlib import nullcontext
from pathlib import Path
from typing import Callable

import requests
import wandb
from pytest import MonkeyPatch, fixture, mark, raises, skip
from pytest_mock import MockerFixture
from wandb import Api
from wandb._strutils import nameof
from wandb.errors import CommError
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.artifacts._generated import (
    ArtifactByName,
    ArtifactFragment,
    ArtifactMembershipByName,
    ArtifactMembershipFragment,
    FetchOrgInfoFromEntity,
)
from wandb.sdk.artifacts._gqlutils import server_supports
from wandb.sdk.artifacts.exceptions import ArtifactFinalizedError
from wandb.sdk.lib.paths import StrPath


@fixture
def sample_data(user: str) -> None:
    """Generate some sample artifacts for tests in this module."""
    # NOTE: Requesting the `user` fixture is important as it sets auth
    # environment variables for the duration of the test.
    _ = user

    with wandb.init(id="first_run", settings={"silent": True}) as run:
        artifact = wandb.Artifact("mnist", type="dataset")
        with artifact.new_file("digits.h5") as f:
            f.write("v0")
        run.log_artifact(artifact, aliases=["my_alias"])

        artifact = wandb.Artifact("mnist", type="dataset")
        table = wandb.Table(
            columns=["c1", "c2"],
            data=[
                ("r1c1", "r1c2"),
                ("r2c1", "r2c2"),
            ],
        )
        artifact.add(table, name="t")
        run.log_artifact(artifact)

    with wandb.init(id="second_run", settings={"silent": True}) as run:
        run.use_artifact("mnist:v0")
        run.use_artifact("mnist:v1")


@mark.usefixtures("sample_data")
def test_artifact_versions(api: Api):
    versions = api.artifact_versions("dataset", "mnist")
    assert len(versions) == 2
    assert {version.name for version in versions} == {"mnist:v0", "mnist:v1"}


@mark.usefixtures("sample_data")
def test_artifact_type(api: Api):
    atype = api.artifact_type("dataset")
    assert atype.name == "dataset"
    col = atype.collection("mnist")
    assert col.name == "mnist"


@mark.usefixtures("sample_data")
def test_artifact_type_collections(api: Api):
    atype = api.artifact_type("dataset")

    # creating a new artifact
    artifact_name = "another-collection"
    artifact = wandb.Artifact(name=artifact_name, type="dataset")
    with artifact.new_file("file.txt") as f:
        f.write("test")
    artifact.save()
    artifact.wait()

    cols = atype.collections()
    assert len(cols) == 2
    assert (cols[0].name == "mnist" and cols[1].name == "another-collection") or (
        cols[0].name == "another-collection" and cols[1].name == "mnist"
    )
    cols = atype.collections(filters={"name": "mnist"})
    assert len(cols) == 1 and cols[0].name == "mnist"
    if server_supports(api.client, pb.ARTIFACT_COLLECTIONS_FILTERING_SORTING):
        cols = atype.collections(order="name")
        assert len(cols) == 2
        assert cols[0].name == "another-collection" and cols[1].name == "mnist"
    else:
        with raises(
            CommError,
            match="Custom ordering of artifact collections is not supported on this wandb server version.",
        ):
            atype.collections(order="name")


@mark.usefixtures("sample_data")
def test_artifact_types(api: Api):
    atypes = api.artifact_types()
    assert {atype.name for atype in atypes} == {"dataset"}


@mark.usefixtures("sample_data")
def test_artifact_get_path(api: Api):
    art = api.artifact("mnist:v0", type="dataset")
    assert art.type == "dataset"
    assert art.name == "mnist:v0"
    actual_path = art.get_entry("digits.h5").download()
    part = art.name
    if platform.system() == "Windows":
        part = "mnist-v0"
    expected_path = os.path.join(".", "artifacts", part, "digits.h5")
    assert actual_path == os.path.abspath(expected_path)


@mark.usefixtures("sample_data")
def test_artifact_get_path_download(api: Api):
    art = api.artifact("mnist:v0", type="dataset")
    path = art.get_entry("digits.h5").download(os.getcwd())
    assert os.path.exists("./digits.h5")
    assert path == os.path.join(os.getcwd(), "digits.h5")


@mark.usefixtures("sample_data")
def test_artifact_file(api: Api):
    art = api.artifact("mnist:v0", type="dataset")
    path = art.file()
    expected_subpath = "mnist-v0" if (platform.system() == "Windows") else "mnist:v0"
    assert path == os.path.join(".", "artifacts", expected_subpath, "digits.h5")


@mark.usefixtures("sample_data")
def test_artifact_files(api: Api):
    art = api.artifact("mnist:v0", type="dataset")
    if server_supports(api.client, pb.TOTAL_COUNT_IN_FILE_CONNECTION):
        assert (
            str(art.files())
            == f"<ArtifactFiles {art.entity}/uncategorized/mnist:v0 (1)>"
        )
    else:
        assert (
            str(art.files()) == f"<ArtifactFiles {art.entity}/uncategorized/mnist:v0>"
        )
    paths = [f.storage_path for f in art.files()]
    assert paths[0].startswith("wandb_artifacts/")


@mark.usefixtures("sample_data")
def test_artifacts_files_filtered_length(api: Api):
    if not server_supports(api.client, pb.TOTAL_COUNT_IN_FILE_CONNECTION):
        skip("Server doesn't support FileConnection.totalCount")

    # creating a new artifact with files
    artifact_name = "".join(
        random.choice(string.ascii_letters + string.digits) for _ in range(10)
    )
    artifact = wandb.Artifact(name=artifact_name, type="text")
    number_of_files = 10
    for i in range(number_of_files):
        with artifact.new_file(f"file{i}.txt") as f:
            f.write(str(i))
    artifact.save()
    artifact.wait()

    assert_artifact = api.artifact(artifact.qualified_name)
    assert len(assert_artifact.files()) == number_of_files
    assert len(assert_artifact.files(names=["file0.txt"])) == 1
    assert len(assert_artifact.files(names=["file0.txt", "file1.txt"])) == 2


@mark.usefixtures("sample_data")
def test_artifact_download(api: Api):
    art = api.artifact("mnist:v0", type="dataset")
    path = art.download()
    if platform.system() == "Windows":
        part = "mnist-v0"
    else:
        part = "mnist:v0"
    assert path == os.path.abspath(os.path.join(".", "artifacts", part))
    assert os.listdir(path) == ["digits.h5"]


@mark.usefixtures("sample_data")
def test_artifact_exists(api: Api):
    assert api.artifact_exists("mnist:v0") is True
    assert api.artifact_exists("mnist:v2") is False
    assert api.artifact_exists("mnist-fake:v0") is False


@mark.usefixtures("sample_data")
def test_artifact_collection_exists(api: Api):
    assert api.artifact_collection_exists("mnist", "dataset") is True
    assert api.artifact_collection_exists("mnist-fake", "dataset") is False


@mark.usefixtures("sample_data")
def test_artifact_exists_raises_on_timeout(mocker: MockerFixture, api: Api):
    # FIXME: We should really be mocking the GraphQL HTTP requests/responses, NOT the
    # actual python methods, but this is complicated by the fact that we need to instantiate
    # a new Api with a shorter timeout, and that Api makes immediate requests on _instantiation_.
    #
    # Mocking every single one of them makes test setup quite brittle and error prone.
    # Moreover, the interaction between @normalize_exceptions and our home-grown retry
    # logic isn't readily configurable, so this test can easily become flaky and/or timeout.
    # The following will have to do for now.
    mocker.patch.object(api, "_artifact", side_effect=requests.Timeout())

    with raises(CommError) as exc_info:
        api.artifact_exists("mnist:v0")
    assert isinstance(exc_info.value.exc, requests.Timeout)

    with raises(CommError) as exc_info:
        api.artifact_exists("mnist-fake:v0")
    assert isinstance(exc_info.value.exc, requests.Timeout)

    with raises(CommError):
        api.artifact_exists("mnist-fake:v0")
    assert isinstance(exc_info.value.exc, requests.Timeout)


@mark.usefixtures("sample_data")
def test_artifact_collection_exists_raises_on_timeout(mocker: MockerFixture, api: Api):
    # FIXME: We should really be mocking the GraphQL HTTP requests/responses, NOT the
    # actual python methods, but this is complicated by the fact that we need to instantiate
    # a new Api with a shorter timeout, and that Api makes immediate requests on _instantiation_.
    #
    # Mocking every single one of them makes test setup quite brittle and error prone.
    # Moreover, the interaction between @normalize_exceptions and our home-grown retry
    # logic isn't readily configurable, so this test can easily become flaky and/or timeout.
    # The following will have to do for now.
    mocker.patch.object(api, "artifact_collection", side_effect=requests.Timeout())

    with raises(CommError) as exc_info:
        api.artifact_collection_exists("mnist", "dataset")
    assert isinstance(exc_info.value.exc, requests.Timeout)

    with raises(CommError) as exc_info:
        api.artifact_collection_exists("mnist-fake", "dataset")
    assert isinstance(exc_info.value.exc, requests.Timeout)


@mark.usefixtures("sample_data")
def test_artifact_delete(api: Api):
    art = api.artifact("mnist:v0", type="dataset")
    # The artifact has aliases, so fail unless delete_aliases is set.
    with raises(CommError):
        art.delete()
    art.delete(delete_aliases=True)


@mark.usefixtures("sample_data")
def test_artifact_delete_on_linked_artifact(api: Api):
    portfolio = "portfolio_name"

    source_art = api.artifact("mnist:v0", type="dataset")
    source_path = source_art.qualified_name  # Set this now in case state changes

    # Link the artifact
    source_art.link(portfolio)
    linked_path = f"{source_art.entity}/{source_art.project}/{portfolio}:v0"
    linked_art = api.artifact(linked_path)

    # Sanity check
    assert source_path != linked_art.qualified_name
    assert source_path == linked_art.source_qualified_name

    # Deleting the linked instance should remove the link, not the underlying source artifact
    linked_art.delete()

    assert api.artifact_exists(source_path) is True
    assert api.artifact_exists(linked_path) is False


@mark.usefixtures("sample_data")
def test_artifact_checkout(api: Api):
    # Create a file that should be removed as part of checkout
    os.makedirs(os.path.join(".", "artifacts", "mnist"))
    with open(os.path.join(".", "artifacts", "mnist", "bogus"), "w") as f:
        f.write("delete me, i'm a bogus file")

    art = api.artifact("mnist:v0", type="dataset")
    path = art.checkout()
    assert path == os.path.abspath(os.path.join(".", "artifacts", "mnist"))
    assert os.listdir(path) == ["digits.h5"]


@mark.usefixtures("sample_data")
def test_artifact_run_used(api: Api):
    run = api.run("uncategorized/second_run")
    arts = run.used_artifacts()
    assert len(arts) == 2
    assert {art.name for art in arts} == {"mnist:v0", "mnist:v1"}


@mark.usefixtures("sample_data")
def test_artifact_run_logged(api: Api):
    run = api.run("uncategorized/first_run")
    arts = run.logged_artifacts()
    assert len(arts) == 2
    assert {art.name for art in arts} == {"mnist:v0", "mnist:v1"}


@mark.usefixtures("sample_data")
def test_artifact_run_logged_cursor(api: Api):
    artifacts = api.run("uncategorized/first_run").logged_artifacts()
    len_artifacts = len(artifacts)
    count = sum(1 for _ in artifacts)
    assert len_artifacts == count


@mark.usefixtures("sample_data")
def test_artifact_manual_use(api: Api):
    run = api.run("uncategorized/second_run")
    art = api.artifact("mnist:v0", type="dataset")
    run.use_artifact(art)


@mark.usefixtures("sample_data")
def test_artifact_bracket_accessor(api: Api):
    art = api.artifact("mnist:v1", type="dataset")
    assert art["t"].__class__ == wandb.Table
    assert art["s"] is None
    with raises(ArtifactFinalizedError):
        art["s"] = wandb.Table(data=[], columns=[])


@mark.usefixtures("sample_data")
def test_artifact_manual_link(api: Api):
    art = api.artifact("mnist:v0", type="dataset")
    art.link("portfolio_name")


@mark.usefixtures("sample_data")
def test_artifact_manual_error(api: Api):
    run = api.run("uncategorized/first_run")
    art = wandb.Artifact("test", type="dataset")
    with raises(CommError):
        run.log_artifact(art)
    with raises(CommError):
        run.use_artifact(art)
    with raises(CommError):
        run.use_artifact("mnist:v0")
    with raises(CommError):
        run.log_artifact("mnist:v0")


@mark.usefixtures("sample_data")
def test_artifact_verify(api: Api):
    art = api.artifact("mnist:v0", type="dataset")
    art.download()
    art.verify()


def test_artifact_save_norun(
    user: str,
    test_settings: Callable[[], wandb.Settings],
    assets_path: Callable[[StrPath], Path],
):
    im_path = str(assets_path("2x2.png"))
    artifact = wandb.Artifact(type="dataset", name="my-arty")
    wb_image = wandb.Image(im_path, classes=[{"id": 0, "name": "person"}])
    artifact.add(wb_image, "my-image")
    artifact.save(settings=test_settings())


def test_artifact_save_run(
    user: str,
    test_settings: Callable[[], wandb.Settings],
    assets_path: Callable[[StrPath], Path],
):
    im_path = str(assets_path("2x2.png"))
    artifact = wandb.Artifact(type="dataset", name="my-arty")
    wb_image = wandb.Image(im_path, classes=[{"id": 0, "name": "person"}])
    artifact.add(wb_image, "my-image")
    with wandb.init(settings=test_settings()) as _:
        artifact.save()


def test_artifact_save_norun_nosettings(
    user: str,
    assets_path: Callable[[StrPath], Path],
):
    im_path = str(assets_path("2x2.png"))
    artifact = wandb.Artifact(type="dataset", name="my-arty")
    wb_image = wandb.Image(im_path, classes=[{"id": 0, "name": "person"}])
    artifact.add(wb_image, "my-image")
    artifact.save()


def test_parse_artifact_path(user: str, api: Api):
    path = "entity/project/artifact:alias/with/slashes"
    entity, project, name = api._parse_artifact_path(path)
    assert entity == "entity"
    assert project == "project"
    assert name == "artifact:alias/with/slashes"

    path = "entity/project/artifact:alias:with:colons"
    entity, project, name = api._parse_artifact_path(path)
    assert entity == "entity"
    assert project == "project"
    assert name == "artifact:alias:with:colons"

    path = "entity/project/artifact:alias:with:colons/and/slashes"
    entity, project, name = api._parse_artifact_path(path)
    assert entity == "entity"
    assert project == "project"
    assert name == "artifact:alias:with:colons/and/slashes"

    path = "artifact:alias/with:colons:and/slashes"
    entity, project, name = api._parse_artifact_path(path)
    assert entity == api.default_entity
    assert project == "uncategorized"
    assert name == "artifact:alias/with:colons:and/slashes"

    path = "entity/project/artifact"
    entity, project, name = api._parse_artifact_path(path)
    assert entity == "entity"
    assert project == "project"
    assert name == "artifact"


@mark.parametrize(
    (
        "artifact_path",
        "resolve_org_entity_name",
        "is_registry_project",
        "expected_artifact_fetched",
    ),
    (
        (
            "org-name/wandb-registry-model/test-collection:v0",
            "org-entity-name",
            True,
            True,
        ),
        (
            "org-entity-name/wandb-registry-model/test-collection:v0",
            "org-entity-name",
            True,
            True,
        ),
        (
            "wandb-registry-model/test-collection:v0",
            "org-entity-name",
            True,
            True,
        ),
        (
            "potato/wandb-registry-model/test-collection:v0",
            "",
            True,
            False,
        ),
        (
            "potato/not-a-registry-model/test-collection:v0",
            "",
            False,
            True,
        ),
    ),
)
def test_fetch_registry_artifact(
    user,
    wandb_backend_spy,
    api,
    mocker,
    artifact_path,
    resolve_org_entity_name,
    is_registry_project,
    expected_artifact_fetched,
):
    from tests.fixtures.wandb_backend_spy.gql_match import Constant, Matcher

    server_supports_artifact_via_membership = server_supports(
        api.client, pb.PROJECT_ARTIFACT_COLLECTION_MEMBERSHIP
    )

    mocker.patch("wandb.sdk.artifacts.artifact.Artifact._from_attrs")

    # Stub the query for orgEntity name(s)
    mock_org_entity_info_responder = Constant(
        content={
            "data": {
                "entity": {
                    "organization": {
                        "name": "org-name",
                        "orgEntity": {"name": resolve_org_entity_name},
                    },
                    "user": None,
                },
            }
        }
    )
    op_matcher = Matcher(operation=nameof(FetchOrgInfoFromEntity))
    wandb_backend_spy.stub_gql(match=op_matcher, respond=mock_org_entity_info_responder)

    mock_artifact_fragment_data = ArtifactFragment(
        name="test-collection",  # NOTE: relevant
        version_index=0,  # NOTE: relevant
        # ------------------------------------------------------------------------------
        # NOTE: Remaining artifact fields are placeholders and not as relevant to the test
        artifact_type={"name": "model"},
        artifact_sequence={
            "name": "test-collection",
            "project": {
                "name": "orig-project",
                "entity": {"name": "test-team"},
            },
        },
        id="PLACEHOLDER",
        description="PLACEHOLDER",
        tags=[],
        ttl_duration_seconds=-2,
        ttl_is_inherited=False,
        metadata="{}",
        state="COMMITTED",
        size=0,
        digest="FAKE_DIGEST",
        file_count=0,
        commit_hash="PLACEHOLDER",
        created_at="PLACEHOLDER",
        updated_at=None,
        history_step=None,
        # ------------------------------------------------------------------------------
    ).model_dump()

    mock_membership_fragment_data = ArtifactMembershipFragment(
        id="PLACEHOLDER",
        artifact=mock_artifact_fragment_data,
        artifact_collection={
            "__typename": "ArtifactPortfolio",
            "name": "test-collection",
            "project": {
                "name": "wandb-registry-model",  # NOTE: relevant
                "entity": {"name": "org-entity-name"},  # NOTE: relevant
            },
        },
        version_index=1,
        aliases=[{"id": "PLACEHOLDER", "alias": "my-alias"}],
    ).model_dump()

    mock_empty_rsp_data = {"data": {"project": {}}}

    mock_artifact_rsp_data = {
        "data": {
            "project": {
                "artifact": mock_artifact_fragment_data,
            }
        }
    }

    mock_membership_rsp_data = {
        "data": {
            "project": {
                "artifact": mock_artifact_fragment_data,
                "artifactCollectionMembership": mock_membership_fragment_data,
            }
        }
    }

    # Set up the mock response for the appropriate GQL operation
    # Return equivalent payload for either membership or by-name fetches
    if server_supports_artifact_via_membership:
        op_name = nameof(ArtifactMembershipByName)
        mock_rsp = mock_membership_rsp_data
    else:
        op_name = nameof(ArtifactByName)
        mock_rsp = mock_artifact_rsp_data

    # If we aren't simulating a successfully-fetched artifact, override the mock response with an empty one
    if not expected_artifact_fetched:
        mock_rsp = mock_empty_rsp_data

    # Now stub the actual GQL request/response we expect to make
    op_matcher = Matcher(operation=op_name)
    mock_responder = Constant(content=mock_rsp)
    wandb_backend_spy.stub_gql(match=op_matcher, respond=mock_responder)

    expectation = nullcontext() if expected_artifact_fetched else raises(CommError)
    with expectation:
        api.artifact(artifact_path)

    if is_registry_project:
        # Calls may be cached, so we expect at most one call
        assert mock_org_entity_info_responder.total_calls <= 1
    else:
        assert mock_org_entity_info_responder.total_calls == 0

    # Ensure at least one of the artifact queries was exercised
    if expected_artifact_fetched:
        assert mock_responder.total_calls == 1
    else:
        assert mock_responder.total_calls == 0


def test_log_artifact_ignores_wandb_project_env_var(
    user: str,
    api: Api,
    monkeypatch: MonkeyPatch,
):
    """Verify run.log_artifact() uses the run's project, not WANDB_PROJECT.

    Regression test for WB-29463: log_artifact should use the run's actual
    entity/project, not environment variables.
    """
    # Create a run and log an artifact
    with wandb.init(settings={"silent": True}) as run:
        artifact = wandb.Artifact("test-artifact", type="dataset")
        with artifact.new_file("test.txt") as f:
            f.write("test content")
        run.log_artifact(artifact)

    run_path = f"{run.entity}/{run.project}/{run.id}"

    # Set WANDB_PROJECT to a DIFFERENT project (this should be ignored)
    monkeypatch.setenv("WANDB_PROJECT", "nonexistent-project")

    # Retrieve the run via API and try to log the same artifact
    api_run = api.run(run_path)
    art = api.artifact(f"{run.entity}/{run.project}/test-artifact:v0")

    # This should succeed using the run's project, not WANDB_PROJECT
    api_run.log_artifact(art)
