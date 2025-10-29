import os
import platform
import string
from contextlib import nullcontext

import pytest
import requests
import wandb
from wandb._strutils import nameof
from wandb.errors.errors import CommError
from wandb.proto.wandb_internal_pb2 import ServerFeature
from wandb.sdk.artifacts._generated import (
    ArtifactByName,
    ArtifactFragment,
    ArtifactMembershipByName,
    ArtifactMembershipFragment,
)
from wandb.sdk.artifacts._gqlutils import server_supports
from wandb.sdk.artifacts.exceptions import ArtifactFinalizedError
from wandb.sdk.internal.internal_api import Api as InternalApi
import random


@pytest.fixture
def sample_data():
    with wandb.init(id="first_run", settings={"silent": True}):
        artifact = wandb.Artifact("mnist", type="dataset")
        with artifact.new_file("digits.h5") as f:
            f.write("v0")
        wandb.run.log_artifact(artifact, aliases=["my_alias"])

        artifact = wandb.Artifact("mnist", type="dataset")
        table = wandb.Table(
            columns=["c1", "c2"],
            data=[
                ("r1c1", "r1c2"),
                ("r2c1", "r2c2"),
            ],
        )
        artifact.add(table, name="t")
        wandb.run.log_artifact(artifact)

    with wandb.init(id="second_run", settings={"silent": True}):
        wandb.run.use_artifact("mnist:v0")
        wandb.run.use_artifact("mnist:v1")


def test_artifact_versions(user, api, sample_data):
    versions = api.artifact_versions("dataset", "mnist")
    assert len(versions) == 2
    assert {version.name for version in versions} == {"mnist:v0", "mnist:v1"}


def test_artifact_type(user, api, sample_data):
    atype = api.artifact_type("dataset")
    assert atype.name == "dataset"
    col = atype.collection("mnist")
    assert col.name == "mnist"
    cols = atype.collections()
    assert cols[0].name == "mnist"


def test_artifact_types(user, api, sample_data):
    atypes = api.artifact_types()
    assert {atype.name for atype in atypes} == {"dataset"}


def test_artifact_get_path(user, api, sample_data):
    art = api.artifact("mnist:v0", type="dataset")
    assert art.type == "dataset"
    assert art.name == "mnist:v0"
    actual_path = art.get_entry("digits.h5").download()
    part = art.name
    if platform.system() == "Windows":
        part = "mnist-v0"
    expected_path = os.path.join(".", "artifacts", part, "digits.h5")
    assert actual_path == os.path.abspath(expected_path)


def test_artifact_get_path_download(user, api, sample_data):
    art = api.artifact("mnist:v0", type="dataset")
    path = art.get_entry("digits.h5").download(os.getcwd())
    assert os.path.exists("./digits.h5")
    assert path == os.path.join(os.getcwd(), "digits.h5")


def test_artifact_file(user, api, sample_data):
    art = api.artifact("mnist:v0", type="dataset")
    path = art.file()
    if platform.system() == "Windows":
        part = "mnist-v0"
    else:
        part = "mnist:v0"
    assert path == os.path.join(".", "artifacts", part, "digits.h5")


def test_artifact_files(user, api, sample_data, wandb_backend_spy):
    art = api.artifact("mnist:v0", type="dataset")
    if server_supports(api.client, ServerFeature.TOTAL_COUNT_IN_FILE_CONNECTION):
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

    # Assert we don't break legacy local installs
    gql = wandb_backend_spy.gql
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="ServerInfo"),
        gql.once(
            content={
                "data": {
                    "serverInfo": {"cliVersionInfo": {"max_cli_version": "0.12.20"}}
                }
            },
            status=200,
        ),
    )

    api = wandb.Api()
    art = api.artifact("mnist:v0", type="dataset")
    files = art.files(per_page=1)
    assert "storagePath" not in files[0]._attrs.keys()
    assert files.last_response is not None
    assert files.more is True
    assert files.cursor is not None


def test_artifacts_files_filtered_length(user, api, sample_data, wandb_backend_spy):
    if not server_supports(api.client, ServerFeature.TOTAL_COUNT_IN_FILE_CONNECTION):
        pytest.skip()

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

    assert_artifact = wandb.Api().artifact(artifact.qualified_name)
    assert len(assert_artifact.files()) == number_of_files
    assert len(assert_artifact.files(names=["file0.txt"])) == 1
    assert len(assert_artifact.files(names=["file0.txt", "file1.txt"])) == 2


def test_artifact_download(user, api, sample_data):
    art = api.artifact("mnist:v0", type="dataset")
    path = art.download()
    if platform.system() == "Windows":
        part = "mnist-v0"
    else:
        part = "mnist:v0"
    assert path == os.path.abspath(os.path.join(".", "artifacts", part))
    assert os.listdir(path) == ["digits.h5"]


def test_artifact_exists(user, api, sample_data):
    assert api.artifact_exists("mnist:v0") is True
    assert api.artifact_exists("mnist:v2") is False
    assert api.artifact_exists("mnist-fake:v0") is False


def test_artifact_collection_exists(user, api, sample_data):
    assert api.artifact_collection_exists("mnist", "dataset") is True
    assert api.artifact_collection_exists("mnist-fake", "dataset") is False


def test_artifact_exists_raises_on_timeout(mocker, user, api, sample_data):
    # FIXME: We should really be mocking the GraphQL HTTP requests/responses, NOT the
    # actual python methods, but this is complicated by the fact that we need to instantiate
    # a new Api with a shorter timeout, and that Api makes immediate requests on _instantiation_.
    #
    # Mocking every single one of them makes test setup quite brittle and error prone.
    # Moreover, the interaction between @normalize_exceptions and our home-grown retry
    # logic isn't readily configurable, so this test can easily become flaky and/or timeout.
    # The following will have to do for now.
    mocker.patch.object(api, "_artifact", side_effect=requests.Timeout())

    with pytest.raises(CommError) as exc_info:
        api.artifact_exists("mnist:v0")
    assert isinstance(exc_info.value.exc, requests.Timeout)

    with pytest.raises(CommError) as exc_info:
        api.artifact_exists("mnist-fake:v0")
    assert isinstance(exc_info.value.exc, requests.Timeout)

    with pytest.raises(CommError):
        api.artifact_exists("mnist-fake:v0")
    assert isinstance(exc_info.value.exc, requests.Timeout)


def test_artifact_collection_exists_raises_on_timeout(mocker, user, api, sample_data):
    # FIXME: We should really be mocking the GraphQL HTTP requests/responses, NOT the
    # actual python methods, but this is complicated by the fact that we need to instantiate
    # a new Api with a shorter timeout, and that Api makes immediate requests on _instantiation_.
    #
    # Mocking every single one of them makes test setup quite brittle and error prone.
    # Moreover, the interaction between @normalize_exceptions and our home-grown retry
    # logic isn't readily configurable, so this test can easily become flaky and/or timeout.
    # The following will have to do for now.
    mocker.patch.object(api, "artifact_collection", side_effect=requests.Timeout())

    with pytest.raises(CommError) as exc_info:
        api.artifact_collection_exists("mnist", "dataset")
    assert isinstance(exc_info.value.exc, requests.Timeout)

    with pytest.raises(CommError) as exc_info:
        api.artifact_collection_exists("mnist-fake", "dataset")
    assert isinstance(exc_info.value.exc, requests.Timeout)


def test_artifact_delete(user, api, sample_data):
    art = api.artifact("mnist:v0", type="dataset")
    # The artifact has aliases, so fail unless delete_aliases is set.
    with pytest.raises(wandb.errors.CommError):
        art.delete()
    art.delete(delete_aliases=True)


def test_artifact_delete_on_linked_artifact(user, api, sample_data):
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


def test_artifact_checkout(user, api, sample_data):
    # Create a file that should be removed as part of checkout
    os.makedirs(os.path.join(".", "artifacts", "mnist"))
    with open(os.path.join(".", "artifacts", "mnist", "bogus"), "w") as f:
        f.write("delete me, i'm a bogus file")

    art = api.artifact("mnist:v0", type="dataset")
    path = art.checkout()
    assert path == os.path.abspath(os.path.join(".", "artifacts", "mnist"))
    assert os.listdir(path) == ["digits.h5"]


def test_artifact_run_used(user, api, sample_data):
    run = api.run("uncategorized/second_run")
    arts = run.used_artifacts()
    assert len(arts) == 2
    assert {art.name for art in arts} == {"mnist:v0", "mnist:v1"}


def test_artifact_run_logged(user, api, sample_data):
    run = api.run("uncategorized/first_run")
    arts = run.logged_artifacts()
    assert len(arts) == 2
    assert {art.name for art in arts} == {"mnist:v0", "mnist:v1"}


def test_artifact_run_logged_cursor(user, api, sample_data):
    artifacts = api.run("uncategorized/first_run").logged_artifacts()
    count = 0
    for _artifact in artifacts:
        count += 1

    assert len(artifacts) == count


def test_artifact_manual_use(user, api, sample_data):
    run = api.run("uncategorized/second_run")
    art = api.artifact("mnist:v0", type="dataset")
    run.use_artifact(art)


def test_artifact_bracket_accessor(user, api, sample_data):
    art = api.artifact("mnist:v1", type="dataset")
    assert art["t"].__class__ == wandb.Table
    assert art["s"] is None
    with pytest.raises(ArtifactFinalizedError):
        art["s"] = wandb.Table(data=[], columns=[])


def test_artifact_manual_link(user, api, sample_data):
    art = api.artifact("mnist:v0", type="dataset")
    art.link("portfolio_name")


def test_artifact_manual_error(user, api, sample_data):
    run = api.run("uncategorized/first_run")
    art = wandb.Artifact("test", type="dataset")
    with pytest.raises(wandb.CommError):
        run.log_artifact(art)
    with pytest.raises(wandb.CommError):
        run.use_artifact(art)
    with pytest.raises(wandb.CommError):
        run.use_artifact("mnist:v0")
    with pytest.raises(wandb.CommError):
        run.log_artifact("mnist:v0")


def test_artifact_verify(user, api, sample_data):
    art = api.artifact("mnist:v0", type="dataset")
    art.download()
    art.verify()


def test_artifact_save_norun(user, test_settings, assets_path):
    im_path = str(assets_path("2x2.png"))
    artifact = wandb.Artifact(type="dataset", name="my-arty")
    wb_image = wandb.Image(im_path, classes=[{"id": 0, "name": "person"}])
    artifact.add(wb_image, "my-image")
    artifact.save(settings=test_settings())


def test_artifact_save_run(user, test_settings, assets_path):
    im_path = str(assets_path("2x2.png"))
    artifact = wandb.Artifact(type="dataset", name="my-arty")
    wb_image = wandb.Image(im_path, classes=[{"id": 0, "name": "person"}])
    artifact.add(wb_image, "my-image")
    run = wandb.init(settings=test_settings())
    artifact.save()
    run.finish()


def test_artifact_save_norun_nosettings(user, assets_path):
    im_path = str(assets_path("2x2.png"))
    artifact = wandb.Artifact(type="dataset", name="my-arty")
    wb_image = wandb.Image(im_path, classes=[{"id": 0, "name": "person"}])
    artifact.add(wb_image, "my-image")
    artifact.save()


def test_parse_artifact_path(user, api):
    entity, project, path = api._parse_artifact_path(
        "entity/project/artifact:alias/with/slashes"
    )
    assert (
        entity == "entity"
        and project == "project"
        and path == "artifact:alias/with/slashes"
    )

    entity, project, path = api._parse_artifact_path(
        "entity/project/artifact:alias:with:colons"
    )
    assert (
        entity == "entity"
        and project == "project"
        and path == "artifact:alias:with:colons"
    )

    entity, project, path = api._parse_artifact_path(
        "entity/project/artifact:alias:with:colons/and/slashes"
    )
    assert (
        entity == "entity"
        and project == "project"
        and path == "artifact:alias:with:colons/and/slashes"
    )

    entity, project, path = api._parse_artifact_path(
        "artifact:alias/with:colons:and/slashes"
    )
    assert path == "artifact:alias/with:colons:and/slashes"

    entity, project, path = api._parse_artifact_path("entity/project/artifact")
    assert entity == "entity" and project == "project" and path == "artifact"


@pytest.mark.parametrize(
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
    server_supports_artifact_via_membership = InternalApi()._server_supports(
        ServerFeature.PROJECT_ARTIFACT_COLLECTION_MEMBERSHIP
    )

    mocker.patch("wandb.sdk.artifacts.artifact.Artifact._from_attrs")

    mock__resolve_org_entity_name = mocker.patch(
        "wandb.sdk.internal.internal_api.Api._resolve_org_entity_name",
        return_value=resolve_org_entity_name,
    )

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
        metadata="{}",
        state="COMMITTED",
        size=0,
        digest="FAKE_DIGEST",
        file_count=0,
        commit_hash="PLACEHOLDER",
        created_at="PLACEHOLDER",
        updated_at=None,
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
    op_matcher = wandb_backend_spy.gql.Matcher(operation=op_name)
    mock_responder = wandb_backend_spy.gql.Constant(content=mock_rsp)
    wandb_backend_spy.stub_gql(match=op_matcher, respond=mock_responder)

    expectation = (
        nullcontext()
        if expected_artifact_fetched
        else pytest.raises(wandb.errors.CommError)
    )
    with expectation:
        api.artifact(artifact_path)

    if is_registry_project:
        mock__resolve_org_entity_name.assert_called_once()
    else:
        mock__resolve_org_entity_name.assert_not_called()

    # Ensure at least one of the artifact queries was exercised
    assert mock_responder.total_calls == 1
