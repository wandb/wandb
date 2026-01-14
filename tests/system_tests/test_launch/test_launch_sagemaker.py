from unittest.mock import MagicMock

import pytest
import wandb
from wandb.apis.internal import Api
from wandb.sdk.launch import loader
from wandb.sdk.launch._project_spec import EntryPoint, LaunchProject
from wandb.sdk.launch.environment.aws_environment import AwsEnvironment


@pytest.fixture
def mock_sagemaker_environment():
    """Mock an instance of the AwsEnvironment class."""
    environment = MagicMock()
    client = MagicMock()
    session = MagicMock()
    session.client.return_value = client
    environment.get_session.return_value = session
    environment.get_region.return_value = "us-east-1"


@pytest.mark.asyncio
@pytest.mark.parametrize("override_entrypoint", [None, ["python", "test.py"]])
async def test_sagemaker_resolved_submitted_job(
    monkeypatch,
    user,
    override_entrypoint,
):
    async def mock_launch_sagemaker_job(*args, **kwargs):
        # return second arg, which is constructed sagemaker create_training_job request
        return args[1]

    mock_env = MagicMock(spec=AwsEnvironment)
    session = MagicMock()
    mock_env.get_session.return_value = session
    monkeypatch.setattr(
        wandb.sdk.launch.loader,
        "environment_from_config",
        lambda *args: mock_env,
    )
    monkeypatch.setattr(
        wandb.sdk.launch.loader,
        "builder_from_config",
        lambda *args: MagicMock(),
    )
    monkeypatch.setattr(
        wandb.sdk.launch.loader,
        "registry_from_config",
        lambda *args: None,
    )

    monkeypatch.setattr(
        "wandb.sdk.launch.runner.sagemaker_runner.launch_sagemaker_job",
        mock_launch_sagemaker_job,
    )

    monkeypatch.setattr(
        "wandb.sdk.launch.runner.local_container.docker_image_exists",
        lambda x: None,
    )
    monkeypatch.setattr(
        "wandb.sdk.launch.runner.local_container.pull_docker_image",
        lambda x: None,
    )
    monkeypatch.setattr(
        "wandb.sdk.launch.builder.noop.NoOpBuilder.build_image",
        lambda *args, **kwargs: "testimage",
    )

    entity_name = "test_entity"
    project_name = "test_project"
    entry_command = ["python", "test.py"]

    # test with user provided image
    project = MagicMock()
    project.fill_macros = LaunchProject.fill_macros.__get__(project, MagicMock)
    entrypoint = EntryPoint("blah", entry_command)
    project.resource_args = {
        "sagemaker": {
            "RoleArn": "my-fake-RoleArn",
            "OutputDataConfig": {"S3OutputPath": "s3://blah/blah"},
            "ResourceConfig": {"blah": 2},
            "StoppingCondition": {"test": 1},
            "TrainingJobName": "${project_name}-${run_id}",
        }
    }
    project.target_entity = entity_name
    project.target_project = project_name
    project.name = None
    project.run_id = "asdasd"
    project.sweep_id = "sweeeeep"
    project.override_config = {}
    project.get_job_entry_point.return_value = entrypoint
    if override_entrypoint:
        project.override_entrypoint = EntryPoint("blah2", override_entrypoint)
    else:
        project.override_entrypoint = None
    project._entrypoint = entrypoint
    project.override_args = ["--a1", "20", "--a2", "10"]
    project.override_files = {}
    project.docker_image = "testimage"
    project.image_name = "testimage"
    project.job = "testjob"
    project.launch_spec = {}
    project.queue_name = None
    project.queue_entity = None
    project.run_queue_item_id = None
    project.get_env_vars_dict = lambda *args, **kwargs: {
        "WANDB_API_KEY": user,
        "WANDB_PROJECT": project_name,
        "WANDB_ENTITY": entity_name,
        "WANDB_LAUNCH": "True",
        "WANDB_RUN_ID": "asdasd",
        "WANDB_DOCKER": "testimage",
        "WANDB_SWEEP_ID": "sweeeeep",
        "WANDB_CONFIG": "{}",
        "WANDB_LAUNCH_FILE_OVERRIDES": "{}",
        "WANDB_ARTIFACTS": '{"_wandb_job": "testjob"}',
        "WANDB_BASE_URL": "",
    }
    environment = loader.environment_from_config({})
    api = Api()
    runner = loader.runner_from_config(
        "sagemaker",
        api,
        {"type": "sagemaker", "SYNCHRONOUS": False},
        environment,
        MagicMock(),
    )
    req = await runner.run(project, project.docker_image)

    assert "my-fake-RoleArn" in req["RoleArn"]
    assert req["AlgorithmSpecification"] == {
        "TrainingImage": "testimage",
        "TrainingInputMode": "File",
        "ContainerEntrypoint": override_entrypoint or entrypoint.command,
        "ContainerArguments": ["--a1", "20", "--a2", "10"],
    }
    assert req["ResourceConfig"] == {"blah": 2}
    assert req["StoppingCondition"] == {"test": 1}
    assert req["TrainingJobName"] == f"{project_name}-{project.run_id}"
    env = req["Environment"]
    env.pop("WANDB_BASE_URL")
    assert env == {
        "WANDB_API_KEY": user,
        "WANDB_PROJECT": "test_project",
        "WANDB_ENTITY": "test_entity",
        "WANDB_LAUNCH": "True",
        "WANDB_RUN_ID": "asdasd",
        "WANDB_DOCKER": "testimage",
        "WANDB_SWEEP_ID": "sweeeeep",
        "WANDB_CONFIG": "{}",
        "WANDB_LAUNCH_FILE_OVERRIDES": "{}",
        "WANDB_ARTIFACTS": '{"_wandb_job": "testjob"}',
    }
