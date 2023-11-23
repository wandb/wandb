import os
import platform

import pytest
import wandb
from tests.pytest_tests.unit_tests_old import utils
from wandb.sdk.artifacts.exceptions import ArtifactFinalizedError


def test_artifact_versions(runner, mock_server, api):
    versions = api.artifact_versions("dataset", "mnist")
    assert len(versions) == 2
    assert versions[0].name == "mnist:v0"
    assert versions[1].name == "mnist:v1"


def test_artifact_type(runner, mock_server, api):
    atype = api.artifact_type("dataset")
    assert atype.name == "dataset"
    col = atype.collection("mnist")
    assert col.name == "mnist"
    cols = atype.collections()
    assert cols[0].name == "mnist"


def test_artifact_types(runner, mock_server, api):
    atypes = api.artifact_types("dataset")

    raised = False
    try:
        assert len(atypes) == 2
    except ValueError:
        raised = True
    assert raised
    assert atypes[0].name == "dataset"


def test_artifact_get_path(runner, mock_server, api):
    art = api.artifact("entity/project/mnist:v0", type="dataset")
    assert art.type == "dataset"
    assert art.name == "mnist:v0"
    with runner.isolated_filesystem():
        path = art.get_entry("digits.h5")
        res = path.download()
        part = art.name
        if platform.system() == "Windows":
            part = "mnist-v0"
        path = os.path.join(".", "artifacts", part, "digits.h5")
        assert res == os.path.abspath(path)


def test_artifact_get_path_download(runner, mock_server, api):
    with runner.isolated_filesystem():
        art = api.artifact("entity/project/mnist:v0", type="dataset")
        path = art.get_entry("digits.h5").download(os.getcwd())
        assert os.path.exists("./digits.h5")
        assert path == os.path.join(os.getcwd(), "digits.h5")


def test_artifact_file(runner, mock_server, api):
    with runner.isolated_filesystem():
        art = api.artifact("entity/project/mnist:v0", type="dataset")
        path = art.file()
        if platform.system() == "Windows":
            part = "mnist-v0"
        else:
            part = "mnist:v0"
        assert path == os.path.join(".", "artifacts", part, "digits.h5")


def test_artifact_files(runner, mock_server, api):
    with runner.isolated_filesystem():
        mock_server.ctx["max_cli_version"] = "0.12.21"
        art = api.artifact("entity/project/mnist:v0", type="dataset")
        assert str(art.files()) == "<ArtifactFiles entity/project/mnist:v0 (10)>"
        paths = [f.storage_path for f in art.files()]
        assert paths == ["x/y/z", "x/y/z"]
        # Assert we don't break legacy local installs
        mock_server.ctx["max_cli_version"] = "0.12.20"
        # reset server info
        art._client._server_info = None
        file = art.files()[0]
        assert "storagePath" not in file._attrs.keys()


@pytest.mark.nexus_failure(feature="artifacts")
@pytest.mark.skipif(platform.system() == "Windows", reason="TODO: fix on windows")
def test_artifact_download(runner, mock_server, api, mocked_run):
    wandb.run = mocked_run
    with runner.isolated_filesystem():
        art = api.artifact("entity/project/mnist:v0", type="dataset")
        path = art.download()
        if platform.system() == "Windows":
            part = "mnist-v0"
        else:
            part = "mnist:v0"
        assert path == os.path.abspath(os.path.join(".", "artifacts", part))
        assert os.listdir(path) == ["digits.h5"]


def test_artifact_delete(runner, mock_server, api):
    with runner.isolated_filesystem():
        art = api.artifact("entity/project/mnist:v0", type="dataset")

        # The artifact has aliases, so fail unless delete_aliases is set.
        # TODO: this was taking 30+ seconds so removing for now...
        # with pytest.raises(Exception):
        #    art.delete()

        art.delete(delete_aliases=True)


@pytest.mark.nexus_failure(feature="artifacts")
def test_artifact_checkout(runner, mock_server, api, mocked_run):
    wandb.run = mocked_run
    with runner.isolated_filesystem():
        # Create a file that should be removed as part of checkout
        os.makedirs(os.path.join(".", "artifacts", "mnist"))
        with open(os.path.join(".", "artifacts", "mnist", "bogus"), "w") as f:
            f.write("delete me, i'm a bogus file")

        art = api.artifact("entity/project/mnist:v0", type="dataset")
        path = art.checkout()
        assert path == os.path.abspath(os.path.join(".", "artifacts", "mnist"))
        assert os.listdir(path) == ["digits.h5"]


def test_artifact_run_used(runner, mock_server, api):
    run = api.run("test/test/test")
    arts = run.used_artifacts()
    assert len(arts) == 2
    assert arts[0].name == "mnist:v0"


def test_artifact_run_logged(runner, mock_server, api):
    run = api.run("test/test/test")
    arts = run.logged_artifacts()
    assert len(arts) == 2
    assert arts[0].name == "mnist:v0"


def test_artifact_run_logged_cursor(runner, mock_server, api):
    artifacts = api.run("test/test/test").logged_artifacts()
    count = 0
    for artifact in artifacts:
        count += 1

    assert len(artifacts) == count


def test_artifact_manual_use(runner, mock_server, api):
    run = api.run("test/test/test")
    art = api.artifact("entity/project/mnist:v0", type="dataset")
    run.use_artifact(art)
    assert True


@pytest.mark.nexus_failure(feature="artifacts")
def test_artifact_bracket_accessor(runner, live_mock_server, api):
    art = api.artifact("entity/project/dummy:v0", type="dataset")
    assert art["t"].__class__ == wandb.Table
    assert art["s"] is None
    # TODO: Remove this once we support incremental adds
    with pytest.raises(ArtifactFinalizedError):
        art["s"] = wandb.Table(data=[], columns=[])


def test_artifact_manual_link(runner, mock_server, api):
    run = api.run("test/test/test")
    art = api.artifact("entity/project/mnist:v0", type="dataset")
    with pytest.raises(wandb.CommError):
        art.link("portfolio_name:latest")


def test_artifact_manual_error(runner, mock_server, api):
    run = api.run("test/test/test")
    art = wandb.Artifact("test", type="dataset")
    with pytest.raises(wandb.CommError):
        run.log_artifact(art)
    with pytest.raises(wandb.CommError):
        run.use_artifact(art)
    with pytest.raises(wandb.CommError):
        run.use_artifact("entity/project/mnist:v0")
    with pytest.raises(wandb.CommError):
        run.log_artifact("entity/project/mnist:v0")


@pytest.mark.skipif(
    platform.system() == "Windows", reason="Verify is broken on Windows"
)
@pytest.mark.nexus_failure(feature="artifacts")
def test_artifact_verify(runner, mock_server, api, mocked_run):
    wandb.run = mocked_run
    art = api.artifact("entity/project/mnist:v0", type="dataset")
    art.download()
    with pytest.raises(ValueError):
        art.verify()


def test_artifact_save_norun(runner, mock_server, test_settings):
    im_path = utils.assets_path("2x2.png")
    with runner.isolated_filesystem():
        artifact = wandb.Artifact(type="dataset", name="my-arty")
        wb_image = wandb.Image(im_path, classes=[{"id": 0, "name": "person"}])
        artifact.add(wb_image, "my-image")
        artifact.save(settings=test_settings)


def test_artifact_save_run(runner, mock_server, test_settings):
    im_path = utils.assets_path("2x2.png")
    with runner.isolated_filesystem():
        artifact = wandb.Artifact(type="dataset", name="my-arty")
        wb_image = wandb.Image(im_path, classes=[{"id": 0, "name": "person"}])
        artifact.add(wb_image, "my-image")
        run = wandb.init(settings=test_settings)
        artifact.save()
        run.finish()


def test_artifact_save_norun_nosettings(runner, mock_server, test_settings):
    im_path = utils.assets_path("2x2.png")
    with runner.isolated_filesystem():
        artifact = wandb.Artifact(type="dataset", name="my-arty")
        wb_image = wandb.Image(im_path, classes=[{"id": 0, "name": "person"}])
        artifact.add(wb_image, "my-image")
        artifact.save()
