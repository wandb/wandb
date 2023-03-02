from unittest.mock import MagicMock

from wandb.sdk.launch._project_spec import LaunchProject

# TODO: parameterize to test other sources
def test_project_image_source_string():
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
        "cuda": None,
        "run_id": None,
    }

    project = LaunchProject(**mock_args)
    project._job_artifact = MagicMock()
    project._job_artifact.name = "mock-test-entity/mock-test-project/mock-test-job"
    project._job_artifact.version = "0"
    assert (
        project.get_image_source_string()
        == "mock-test-entity/mock-test-project/mock-test-job:v0"
    )
