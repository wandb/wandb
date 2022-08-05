"""These test the high level sdk methods by mocking out the backend.
See wandb_integration_test.py for tests that launch a real backend against
a live backend server.
"""
import os
import pytest
import wandb


@pytest.mark.wandb_args(k8s=True)
def test_k8s_success(wandb_init_run):
    assert wandb.run._settings.docker == "test@sha256:1234"


@pytest.mark.wandb_args(k8s=False)
def test_k8s_failure(wandb_init_run):
    assert wandb.run._settings.docker is None


@pytest.mark.wandb_args(sagemaker=True)
def test_sagemaker(wandb_init_run, git_repo):
    assert wandb.config.foo == "bar"
    assert wandb.run.id == "sage-maker"
    # TODO: add test for secret, but for now there is no env or setting for it
    #  so its not added. Similarly add test for group
    # assert os.getenv("WANDB_TEST_SECRET") == "TRUE"
    # assert wandb.run.group == "sage"


def test_login_sets_api_base_url(mock_server):
    base_url = "https://api.test.host.ai"
    wandb.login(anonymous="must", host=base_url)
    api = wandb.Api()
    assert api.settings["base_url"] == base_url
    base_url = "https://api.wandb.ai"
    wandb.login(anonymous="must", host=base_url)
    api = wandb.Api()
    assert api.settings["base_url"] == base_url


def test_restore_no_init(runner, mock_server):
    with runner.isolated_filesystem():
        mock_server.set_context("files", {"weights.h5": 10000})
        res = wandb.restore("weights.h5", run_path="foo/bar/baz")
        assert os.path.getsize(res.name) == 10000


def test_restore(runner, mock_server, wandb_init_run):
    with runner.isolated_filesystem():
        mock_server.set_context("files", {"weights.h5": 10000})
        res = wandb.restore("weights.h5")
        assert os.path.getsize(res.name) == 10000


def test_restore_name_not_found(runner, mock_server, wandb_init_run):
    with runner.isolated_filesystem():
        with pytest.raises(ValueError):
            wandb.restore("nofile.h5")
