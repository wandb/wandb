"""These test the high level sdk methods by mocking out the backend.
See wandb_integration_test.py for tests that launch a real backend against
a live backend server.
"""
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
