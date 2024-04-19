import os
from unittest.mock import MagicMock

from wandb.sdk.launch._project_spec import LaunchProject


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
