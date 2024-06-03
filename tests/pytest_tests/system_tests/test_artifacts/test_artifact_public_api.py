import os
import platform

import pytest

import wandb
from wandb.sdk.artifacts.exceptions import ArtifactFinalizedError


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


def test_artifact_files(user, api, sample_data, relay_server, inject_graphql_response):
    art = api.artifact("mnist:v0", type="dataset")
    assert (
        str(art.files()) == f"<ArtifactFiles {art.entity}/uncategorized/mnist:v0 (1)>"
    )
    paths = [f.storage_path for f in art.files()]
    assert paths[0].startswith("wandb_artifacts/")

    # Assert we don't break legacy local installs
    server_info_response = inject_graphql_response(
        # request
        query_match_fn=lambda query, variables: query.startswith("query ServerInfo"),
        # response
        body="""{"data": {"serverInfo": {"cliVersionInfo": {"max_cli_version": "0.12.20"}}}}""",
    )
    with relay_server(inject=[server_info_response]):
        api = wandb.Api()
        art = api.artifact("mnist:v0", type="dataset")
        file = art.files()[0]
        assert "storagePath" not in file._attrs.keys()


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
    assert api.artifact_exists("mnist:v0")
    assert not api.artifact_exists("mnist:v2")
    assert not api.artifact_exists("mnist-fake:v0")


def test_artifact_collection_exists(user, api, sample_data):
    assert api.artifact_collection_exists("mnist", "dataset")
    assert not api.artifact_collection_exists("mnist-fake", "dataset")


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
