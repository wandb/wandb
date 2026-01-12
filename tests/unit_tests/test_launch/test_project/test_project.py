from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest
from wandb.sdk.launch._project_spec import LaunchProject, LaunchSource


def test_project_build_required():
    mock_args = {
        "job": "mock-test-entity/mock-test-project/mock-test-job:v0",
        "api": MagicMock(),
        "launch_spec": {},
        "target_entity": "mock-test-entity",
        "target_project": "mock-test-project",
        "docker_config": {},
        "overrides": {},
        "git_info": {},
        "resource": "local-container",
        "resource_args": {},
        "uri": None,
        "name": None,
        "run_id": None,
    }
    project = LaunchProject(**mock_args)

    assert project.build_required() is False

    mock_args.update(
        {"job": None, "docker_config": {"docker_image": "mock-test-image:v0"}}
    )
    project = LaunchProject(**mock_args)
    assert project.build_required() is True


# TODO: parameterize to test other sources
def test_project_image_source_string():
    job_name = "mock-test-entity/mock-test-project/mock-test-job"
    job_version = 0
    mock_args = {
        "job": "mock-test-entity/mock-test-project/mock-test-job:v0",
        "api": MagicMock(),
        "launch_spec": {},
        "target_entity": "mock-test-entity",
        "target_project": "mock-test-project",
        "docker_config": {},
        "overrides": {},
        "git_info": {},
        "resource": "local-container",
        "resource_args": {},
        "uri": None,
        "name": None,
        "run_id": None,
    }

    project = LaunchProject(**mock_args)
    project._job_artifact = MagicMock()
    project._job_artifact.name = job_name
    project._job_artifact.version = job_version
    assert project.get_image_source_string() == f"{job_name}:v{job_version}"


def test_project_fill_macros():
    """Test that macros are substituted correctly."""
    os.environ["CUDA_VISIBLE_DEVICES"] = "0,1,2,3"
    project = LaunchProject(
        job="mock-test-entity/mock-test-project/mock-test-job:v0",
        api=MagicMock(),
        launch_spec={"author": "test-user"},
        target_entity="mock-test-entity",
        target_project="mock-test-project",
        docker_config={},
        overrides={},
        git_info={},
        resource="local-container",
        resource_args={
            "kubernetes": {
                "labels": [
                    {"key": "wandb-project", "value": "${project_name}"},
                    {"key": "wandb-entity", "value": "${entity_name}"},
                    {"key": "wandb-author", "value": "${author}"},
                ],
                "jobName": "launch-job-${run_id}",
                "gpus": "${CUDA_VISIBLE_DEVICES}",
                "image": "${image_uri}",
            }
        },
        uri=None,
        name=None,
        run_id="my-run-id",
    )
    resource_args = project.fill_macros("my-custom-image")
    assert resource_args["kubernetes"]["labels"] == [
        {"key": "wandb-project", "value": "mock-test-project"},
        {"key": "wandb-entity", "value": "mock-test-entity"},
        {"key": "wandb-author", "value": "test-user"},
    ]
    assert resource_args["kubernetes"]["jobName"] == "launch-job-my-run-id"
    assert resource_args["kubernetes"]["gpus"] == "0,1,2,3"
    assert resource_args["kubernetes"]["image"] == "my-custom-image"


def test_project_fetch_and_validate_project_job():
    mock_args = {
        "uri": None,
        "job": "mock-test-entity/mock-test-project/mock-test-job:v0",
        "api": MagicMock(),
        "launch_spec": {},
        "target_entity": "mock-test-entity",
        "target_project": "mock-test-project",
        "docker_config": {},
        "overrides": {},
        "git_info": {},
        "resource": "local-container",
        "resource_args": {},
        "name": None,
        "run_id": None,
    }
    project = LaunchProject(**mock_args)
    project._fetch_job = MagicMock()
    project.fetch_and_validate_project()
    assert project._fetch_job.called


def test_project_fetch_and_validate_project_docker_image():
    mock_args = {
        "job": None,
        "api": MagicMock(),
        "launch_spec": {"image_uri": "mock-test-image:v0"},
        "target_entity": "mock-test-entity",
        "target_project": "mock-test-project",
        "docker_config": {},
        "overrides": {},
        "git_info": {},
        "resource": "local-container",
        "resource_args": {},
        "uri": None,
        "name": None,
        "run_id": None,
    }
    project = LaunchProject(**mock_args)
    project._fetch_job = MagicMock()
    project.fetch_and_validate_project()

    project._fetch_job.assert_not_called()


def test_project_parse_existing_requirements(mocker, tmp_path):
    mocker.termwarn = MagicMock()
    mocker.patch("wandb.termwarn", mocker.termwarn)
    mock_args = {
        "job": None,
        "api": MagicMock(),
        "launch_spec": {"image_uri": "mock-test-image:v0"},
        "target_entity": "mock-test-entity",
        "target_project": "mock-test-project",
        "docker_config": {},
        "overrides": {},
        "git_info": {},
        "resource": "local-container",
        "resource_args": {},
        "uri": None,
        "name": None,
        "run_id": None,
    }
    project = LaunchProject(**mock_args)
    project.project_dir = tmp_path
    (tmp_path / "requirements.txt").write_text("mock-requirement")
    assert (
        # Trailing space in the expected string is intentional.
        project.parse_existing_requirements() == "WANDB_ONLY_INCLUDE=mock-requirement "
    )
    warn_msg = mocker.termwarn.call_args.args[0]
    assert "wandb is not present in requirements.txt." in warn_msg

    # Test with wandb in requirements
    mocker.termwarn.reset_mock()
    (tmp_path / "requirements.txt").write_text("\nwandb")
    project.parse_existing_requirements()
    mocker.termwarn.assert_not_called()


@pytest.fixture
def mock_project_args():
    return {
        "job": None,
        "api": MagicMock(),
        "launch_spec": {"author": "mock-author"},
        "target_entity": "mock-test-entity",
        "target_project": "mock-test-project",
        "docker_config": {"docker_image": "mock-test-image:v0"},
        "overrides": {},
        "git_info": {},
        "resource": "local-container",
        "resource_args": {},
        "uri": None,
        "name": None,
        "run_id": None,
        "sweep_id": "mock-sweep-id",
    }


def test_project_parse_existing_requirements_invalid_requirement(
    tmp_path,
    mock_project_args,
    wandb_caplog,
):
    project = LaunchProject(**mock_project_args)
    project.project_dir = tmp_path
    (tmp_path / "requirements.txt").write_text("invalid requirement")

    project.parse_existing_requirements()

    assert "Unable to parse line" in wandb_caplog.text


def test_get_env_vars_dict(mock_project_args, test_api):
    """Test that env vars are correctly set from a launch project."""
    project = LaunchProject(**mock_project_args)
    project._queue_name = "mock-queue"
    project._queue_entity = "mock-test-entity"
    project._run_queue_item_id = "mock-queue-item-id"

    env_vars = project.get_env_vars_dict(test_api, 512)
    run_id = env_vars.pop("WANDB_RUN_ID")
    assert len(run_id) == 8
    assert env_vars == {
        "WANDB_API_KEY": None,
        "WANDB_ARTIFACTS": "{}",
        "WANDB_BASE_URL": "https://api.wandb.ai",
        "WANDB_CONFIG": "{}",
        "WANDB_DOCKER": "mock-test-image:v0",
        "WANDB_ENTITY": "mock-test-entity",
        "WANDB_LAUNCH": "True",
        "WANDB_LAUNCH_FILE_OVERRIDES": "{}",
        "WANDB_LAUNCH_QUEUE_ENTITY": "mock-test-entity",
        "WANDB_LAUNCH_QUEUE_NAME": "mock-queue",
        "WANDB_LAUNCH_TRACE_ID": "mock-queue-item-id",
        "WANDB_PROJECT": "mock-test-project",
        "WANDB_SWEEP_ID": "mock-sweep-id",
        "WANDB_USERNAME": "mock-author",
    }


def test_get_env_vars_dict_with_low_max_length(mock_project_args, test_api):
    """Test that we break config over multiple env vars when it exceeds the max length."""
    project = LaunchProject(**mock_project_args)
    project.override_config = {
        "learning_rate": 0.01,
        "batch_size": 32,
    }
    env_vars = project.get_env_vars_dict(test_api, 12)
    run_id = env_vars.pop("WANDB_RUN_ID")
    assert len(run_id) == 8
    assert env_vars == {
        "WANDB_API_KEY": None,
        "WANDB_ARTIFACTS": "{}",
        "WANDB_BASE_URL": "https://api.wandb.ai",
        "WANDB_CONFIG_0": '{"learning_r',
        "WANDB_CONFIG_1": 'ate": 0.01, ',
        "WANDB_CONFIG_2": '"batch_size"',
        "WANDB_CONFIG_3": ": 32}",
        "WANDB_DOCKER": "mock-test-image:v0",
        "WANDB_ENTITY": "mock-test-entity",
        "WANDB_LAUNCH": "True",
        "WANDB_LAUNCH_FILE_OVERRIDES": "{}",
        "WANDB_PROJECT": "mock-test-project",
        "WANDB_SWEEP_ID": "mock-sweep-id",
        "WANDB_USERNAME": "mock-author",
    }


def test_init_source_placeholder_uri(mock_project_args):
    """Test that the source placeholder URI is correctly initialized."""
    mock_project_args["uri"] = "placeholder-uri"
    project_1 = LaunchProject(**mock_project_args)
    assert project_1.source == LaunchSource.DOCKER
    mock_project_args["docker_config"] = {}
    project_2 = LaunchProject(**mock_project_args)
    assert project_2.source == LaunchSource.SCHEDULER
