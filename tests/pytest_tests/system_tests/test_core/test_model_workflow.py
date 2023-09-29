import tempfile

import pytest
from wandb import env


class FakeArtifact:
    def is_draft(self):
        return False


def test_offline_link_artifact(wandb_init):
    run = wandb_init(mode="offline")
    with pytest.raises(NotImplementedError):
        run.link_artifact(FakeArtifact(), "entity/project/portfolio", "latest")
    run.finish()


@pytest.mark.nexus_failure(feature="models")
def test_log_model(relay_server, wandb_init):
    with relay_server():
        run = wandb_init()
        with tempfile.TemporaryDirectory(dir="./") as tmpdir:
            with open(tmpdir + "/boom.txt", "w") as f:
                f.write("testing")

            local_path = f"{tmpdir}/boom.txt"
            run.log_model(local_path, model_name="test-model")
        run.finish()

        run = wandb_init()
        download_path = run.use_model("test-model:v0")
        file = download_path
        assert file == f"{env.get_artifact_dir()}/test-model:v0/boom.txt"
        run.finish()


@pytest.mark.nexus_failure(feature="models")
def test_use_model(relay_server, wandb_init):
    with relay_server():
        run = wandb_init()
        with tempfile.TemporaryDirectory(dir="./") as tmpdir:
            with open(tmpdir + "/boom.txt", "w") as f:
                f.write("testing")

            local_path = f"{tmpdir}/boom.txt"
            logged_artifact = run.log_artifact(
                local_path, name="test-model", type="model"
            )
            logged_artifact.wait()
            download_path = run.use_model("test-model:v0")
            file = download_path
            assert file == f"{env.get_artifact_dir()}/test-model:v0/boom.txt"
        run.finish()


@pytest.mark.nexus_failure(feature="models")
def test_use_model_error_artifact_type(relay_server, wandb_init):
    with relay_server():
        run = wandb_init()
        with tempfile.TemporaryDirectory(dir="./") as tmpdir:
            with open(tmpdir + "/boom.txt", "w") as f:
                f.write("testing")

            local_path = f"{tmpdir}/boom.txt"
            logged_artifact = run.log_artifact(
                local_path, name="test-model", type="dataset"
            )
            logged_artifact.wait()
            with pytest.raises(AssertionError):
                _ = run.use_model("test-model:v0")
        run.finish()


@pytest.mark.nexus_failure(feature="models")
def test_link_model(relay_server, wandb_init):
    with relay_server():
        run = wandb_init()
        with tempfile.TemporaryDirectory(dir="./") as tmpdir:
            with open(tmpdir + "/boom.txt", "w") as f:
                f.write("testing")

            local_path = f"{tmpdir}/boom.txt"
            run.link_model(local_path, "test_portfolio", "test_model")
        run.finish()

        run = wandb_init()
        download_path = run.use_model("model-registry/test_portfolio:v0")
        file = download_path
        assert file == f"{env.get_artifact_dir()}/test_model:v0/boom.txt"
        run.finish()
