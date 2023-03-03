import json
import sys
from unittest.mock import MagicMock

import pytest
import wandb
import wandb.sdk.launch._project_spec as _project_spec
import wandb.sdk.launch.launch as launch
from wandb.sdk.launch.environment.aws_environment import AwsEnvironment
from wandb.sdk.launch.runner.sagemaker_runner import SagemakerSubmittedRun
from wandb.sdk.launch.utils import LaunchError

from tests.pytest_tests.unit_tests_old.utils import fixture_open

from .test_launch import mocked_fetchable_git_repo  # noqa: F401


@pytest.fixture
def mock_sagemaker_environment():
    """Mock an instance of the AwsEnvironment class."""
    environment = MagicMock()
    client = MagicMock()
    session = MagicMock()
    session.client.return_value = client
    environment.get_session.return_value = session
    environment.get_region.return_value = "us-east-1"


@pytest.fixture
def mock_ecr():
    """Mock an instance of the ECR class."""
    ecr = MagicMock()


def mock_create_training_job(*args, **kwargs):
    print(kwargs)
    print(f'Project: {kwargs["Environment"]["WANDB_PROJECT"]}')
    print(f'Entity: {kwargs["Environment"]["WANDB_ENTITY"]}')
    print(f'Config: {kwargs["Environment"]["WANDB_CONFIG"]}')
    print(f'Artifacts: {kwargs["Environment"]["WANDB_ARTIFACTS"]}')
    return {
        "TrainingJobArn": "arn:aws:sagemaker:us-east-1:123456789012:TrainingJob/test-job-1",
        **kwargs,
    }


def mock_sagemaker_client():
    mock_sagemaker_client = MagicMock()
    mock_sagemaker_client.create_training_job = mock_create_training_job
    mock_sagemaker_client.create_training_job.return_value = {
        "TrainingJobArn": "arn:aws:sagemaker:us-east-1:123456789012:TrainingJob/test-job-1"
    }
    mock_sagemaker_client.stop_training_job.return_value = {
        "TrainingJobArn": "arn:aws:sagemaker:us-east-1:123456789012:TrainingJob/test-job-1"
    }
    mock_sagemaker_client.describe_training_job.return_value = {
        "TrainingJobStatus": "Completed",
        "TrainingJobName": "test-job-1",
    }
    return mock_sagemaker_client


def test_launch_aws_sagemaker_no_instance(
    live_mock_server,
    test_settings,
    mocked_fetchable_git_repo,
    monkeypatch,
    capsys,
):
    def mock_create_metadata_file(*args, **kwargs):
        dockerfile_contents = args[4]
        expected_entrypoint = 'ENTRYPOINT ["sh", "train"]'
        assert expected_entrypoint in dockerfile_contents, dockerfile_contents
        _project_spec.create_metadata_file(*args, **kwargs)

    monkeypatch.setattr(
        wandb.sdk.launch._project_spec,
        "create_metadata_file",
        mock_create_metadata_file,
    )
    monkeypatch.setattr(wandb.docker, "tag", lambda x, y: "")
    monkeypatch.setattr(
        wandb.docker, "push", lambda x, y: f"The push refers to repository [{x}]"
    )
    mock_env = MagicMock(spec=AwsEnvironment)
    session = MagicMock()
    session.client.return_value = mock_sagemaker_client()
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
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    uri = "https://wandb.ai/mock_server_entity/test/runs/1"
    kwargs = json.loads(fixture_open("launch/launch_sagemaker_config.json").read())
    kwargs["uri"] = uri
    kwargs["api"] = api

    run = launch.run(**kwargs)
    out, _ = capsys.readouterr()
    assert run.training_job_name == "test-job-1"
    assert "Project: test" in out
    assert "Entity: mock_server_entity" in out
    assert "Config: {}" in out
    assert "Artifacts: {}" in out


def test_launch_aws_sagemaker(
    live_mock_server, test_settings, mocked_fetchable_git_repo, monkeypatch, capsys
):
    def mock_create_metadata_file(*args, **kwargs):
        dockerfile_contents = args[4]
        expected_entrypoint = 'ENTRYPOINT ["sh", "train"]'
        assert expected_entrypoint in dockerfile_contents, dockerfile_contents
        _project_spec.create_metadata_file(*args, **kwargs)

    mock_env = MagicMock(spec=AwsEnvironment)
    session = MagicMock()
    session.client.return_value = mock_sagemaker_client()
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
        wandb.sdk.launch._project_spec,
        "create_metadata_file",
        mock_create_metadata_file,
    )
    monkeypatch.setattr(wandb.docker, "tag", lambda x, y: "")
    monkeypatch.setattr(
        wandb.docker, "push", lambda x, y: f"The push refers to repository [{x}]"
    )
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    uri = "https://wandb.ai/mock_server_entity/test/runs/1"
    kwargs = json.loads(fixture_open("launch/launch_sagemaker_config.json").read())
    kwargs["uri"] = uri
    kwargs["api"] = api
    run = launch.run(**kwargs)
    out, _ = capsys.readouterr()
    assert run.training_job_name == "test-job-1"
    assert "Project: test" in out
    assert "Entity: mock_server_entity" in out
    assert "Config: {}" in out
    assert "Artifacts: {}" in out


@pytest.mark.timeout(320)
def test_launch_aws_sagemaker_launch_fail(
    live_mock_server,
    test_settings,
    mocked_fetchable_git_repo,
    monkeypatch,
):
    def mock_client_launch_fail(*args, **kwargs):
        if args[0] == "sagemaker":
            mock_sagemaker_client = MagicMock()
            mock_sagemaker_client.create_training_job.return_value = {}
            mock_sagemaker_client.stop_training_job.return_value = {
                "TrainingJobArn": "arn:aws:sagemaker:us-east-1:123456789012:TrainingJob/test-job-1"
            }
            mock_sagemaker_client.describe_training_job.return_value = {
                "TrainingJobStatus": "Completed",
                "TrainingJobName": "test-job-1",
            }
            return mock_sagemaker_client
        elif args[0] == "ecr":
            ecr_client = MagicMock()
            ecr_client.get_authorization_token.return_value = {
                "authorizationData": [
                    {
                        "proxyEndpoint": "https://123456789012.dkr.ecr.us-east-1.amazonaws.com",
                    }
                ]
            }
            return ecr_client
        elif args[0] == "sts":
            sts_client = MagicMock()
            sts_client.get_caller_identity.return_value = {
                "Account": "123456789012",
            }
            return sts_client

    mock_env = MagicMock(spec=AwsEnvironment)
    session = MagicMock()
    session.client = mock_client_launch_fail
    mock_env.get_session.return_value = session
    monkeypatch.setattr(
        wandb.sdk.launch.loader,
        "environment_from_config",
        lambda *args: mock_env,
    )
    monkeypatch.setattr(wandb.docker, "tag", lambda x, y: "")
    monkeypatch.setattr(
        wandb.docker, "push", lambda x, y: f"The push refers to repository [{x}]"
    )
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    uri = "https://wandb.ai/mock_server_entity/test/runs/1"
    kwargs = json.loads(fixture_open("launch/launch_sagemaker_config.json").read())
    kwargs["uri"] = uri
    kwargs["api"] = api

    with pytest.raises(LaunchError) as e_info:
        launch.run(**kwargs)
    assert "Unable to create training job" in str(e_info.value)


@pytest.mark.skipif(
    sys.version_info < (3, 5),
    reason="wandb launch is not available for python versions < 3.5",
)
def test_sagemaker_specified_image(
    live_mock_server, test_settings, mocked_fetchable_git_repo, monkeypatch, capsys
):
    mock_env = MagicMock(spec=AwsEnvironment)
    session = MagicMock()
    session.client.return_value = mock_sagemaker_client()
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
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    uri = "https://wandb.ai/mock_server_entity/test/runs/1"
    kwargs = json.loads(fixture_open("launch/launch_sagemaker_config.json").read())
    kwargs["uri"] = uri
    kwargs["api"] = api
    kwargs["resource_args"]["sagemaker"]["AlgorithmSpecification"][
        "TrainingImage"
    ] = "my-test-image:latest"
    kwargs["resource_args"]["sagemaker"]["AlgorithmSpecification"][
        "TrainingInputMode"
    ] = "File"
    launch.run(**kwargs)
    out, _ = capsys.readouterr()
    assert "Project: test" in out
    assert "Entity: mock_server_entity" in out
    assert "Config: {}" in out
    assert "Artifacts: {}" in out


def test_aws_submitted_run_status():
    mock_sagemaker_client = MagicMock()
    mock_sagemaker_client.describe_training_job.return_value = {
        "TrainingJobStatus": "InProgress",
    }
    run = SagemakerSubmittedRun("test-job-1", mock_sagemaker_client)
    assert run.get_status().state == "running"

    mock_sagemaker_client.describe_training_job.return_value = {
        "TrainingJobStatus": "Completed",
    }
    run = SagemakerSubmittedRun("test-job-1", mock_sagemaker_client)
    assert run.get_status().state == "finished"

    mock_sagemaker_client.describe_training_job.return_value = {
        "TrainingJobStatus": "Failed",
    }
    run = SagemakerSubmittedRun("test-job-1", mock_sagemaker_client)
    assert run.get_status().state == "failed"

    mock_sagemaker_client.describe_training_job.return_value = {
        "TrainingJobStatus": "Stopped",
    }
    run = SagemakerSubmittedRun("test-job-1", mock_sagemaker_client)
    assert run.get_status().state == "finished"

    mock_sagemaker_client.describe_training_job.return_value = {
        "TrainingJobStatus": "Stopping",
    }
    run = SagemakerSubmittedRun("test-job-1", mock_sagemaker_client)
    assert run.get_status().state == "stopping"


def test_aws_submitted_run_cancel():
    mock_sagemaker_client = MagicMock()
    mock_sagemaker_client.stopping = 0

    def mock_describe_training_job(TrainingJobName):
        if mock_sagemaker_client.stopping == 1:
            mock_sagemaker_client.stopping += 1
            return {
                "TrainingJobStatus": "Stopping",
            }
        elif mock_sagemaker_client.stopping == 2:
            return {
                "TrainingJobStatus": "Stopped",
            }
        else:
            return {
                "TrainingJobStatus": "InProgress",
            }

    def mock_stop_training_job(TrainingJobName):
        mock_sagemaker_client.stopping += 1
        return {
            "TrainingJobStatus": "Stopping",
        }

    mock_sagemaker_client.describe_training_job = mock_describe_training_job
    mock_sagemaker_client.stop_training_job = mock_stop_training_job
    run = SagemakerSubmittedRun("test-job-1", mock_sagemaker_client)
    run.cancel()
    assert run._status.state == "finished"


def test_aws_submitted_run_id():
    run = SagemakerSubmittedRun("test-job-1", None)
    assert run.id == "sagemaker-test-job-1"


def test_no_sagemaker_resource_args(
    runner, live_mock_server, test_settings, mocked_fetchable_git_repo, monkeypatch
):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setattr(
        wandb.docker, "push", lambda x, y: f"The push refers to repository [{x}]"
    )
    mock_env = MagicMock(spec=AwsEnvironment)
    session = MagicMock()
    session.client.return_value = mock_sagemaker_client()
    mock_env.get_session.return_value = session
    monkeypatch.setattr(
        wandb.sdk.launch.loader,
        "environment_from_config",
        lambda *args: mock_env,
    )
    kwargs = json.loads(fixture_open("launch/launch_sagemaker_config.json").read())
    with runner.isolated_filesystem():
        uri = "https://wandb.ai/mock_server_entity/test/runs/1"
        api = wandb.sdk.internal.internal_api.Api(
            default_settings=test_settings, load_settings=False
        )
        kwargs["uri"] = uri
        kwargs["api"] = api
        kwargs["resource_args"].pop("sagemaker", None)
        with pytest.raises(LaunchError) as e_info:
            launch.run(**kwargs)
        assert (
            str(e_info.value)
            == "No sagemaker args specified. Specify sagemaker args in resource_args"
        )


def test_no_OuputDataConfig(
    runner, live_mock_server, test_settings, mocked_fetchable_git_repo, monkeypatch
):
    mock_env = MagicMock(spec=AwsEnvironment)
    session = MagicMock()
    session.client.return_value = mock_sagemaker_client()
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
        "wandb.sdk.launch.launch.LAUNCH_CONFIG_FILE", "./random-nonexistant-file.yaml"
    )
    monkeypatch.setattr(
        wandb.docker, "push", lambda x, y: f"The push refers to repository [{x}]"
    )
    kwargs = json.loads(fixture_open("launch/launch_sagemaker_config.json").read())
    with runner.isolated_filesystem():
        uri = "https://wandb.ai/mock_server_entity/test/runs/1"
        api = wandb.sdk.internal.internal_api.Api(
            default_settings=test_settings, load_settings=False
        )
        kwargs["uri"] = uri
        kwargs["api"] = api
        kwargs["resource_args"]["sagemaker"].pop("OutputDataConfig", None)
        with pytest.raises(LaunchError) as e_info:
            launch.run(**kwargs)
        assert (
            str(e_info.value)
            == "Sagemaker launcher requires an OutputDataConfig Sagemaker resource argument"
        )


def test_no_StoppingCondition(
    runner, live_mock_server, test_settings, mocked_fetchable_git_repo, monkeypatch
):
    mock_env = MagicMock(spec=AwsEnvironment)
    session = MagicMock()
    session.client.return_value = mock_sagemaker_client()
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
        wandb.docker, "push", lambda x, y: f"The push refers to repository [{x}]"
    )
    kwargs = json.loads(fixture_open("launch/launch_sagemaker_config.json").read())
    with runner.isolated_filesystem():
        uri = "https://wandb.ai/mock_server_entity/test/runs/1"
        api = wandb.sdk.internal.internal_api.Api(
            default_settings=test_settings, load_settings=False
        )
        kwargs["uri"] = uri
        kwargs["api"] = api
        kwargs["resource_args"]["sagemaker"].pop("StoppingCondition", None)

        with pytest.raises(LaunchError) as e_info:
            launch.run(**kwargs)
        assert (
            str(e_info.value)
            == "Sagemaker launcher requires a StoppingCondition Sagemaker resource argument"
        )


def test_no_ResourceConfig(
    runner, live_mock_server, test_settings, mocked_fetchable_git_repo, monkeypatch
):
    kwargs = json.loads(fixture_open("launch/launch_sagemaker_config.json").read())
    mock_env = MagicMock(spec=AwsEnvironment)
    session = MagicMock()
    session.client.return_value = mock_sagemaker_client()
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
    with runner.isolated_filesystem():
        uri = "https://wandb.ai/mock_server_entity/test/runs/1"
        api = wandb.sdk.internal.internal_api.Api(
            default_settings=test_settings, load_settings=False
        )
        kwargs["uri"] = uri
        kwargs["api"] = api
        kwargs["resource_args"]["sagemaker"].pop("ResourceConfig", None)

        with pytest.raises(LaunchError) as e_info:
            launch.run(**kwargs)
        assert (
            str(e_info.value)
            == "Sagemaker launcher requires a ResourceConfig Sagemaker resource argument"
        )


def test_no_RoleARN(
    runner, live_mock_server, test_settings, mocked_fetchable_git_repo, monkeypatch
):
    kwargs = json.loads(fixture_open("launch/launch_sagemaker_config.json").read())
    mock_env = MagicMock(spec=AwsEnvironment)
    session = MagicMock()
    session.client.return_value = mock_sagemaker_client()
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
    with runner.isolated_filesystem():
        uri = "https://wandb.ai/mock_server_entity/test/runs/1"
        api = wandb.sdk.internal.internal_api.Api(
            default_settings=test_settings, load_settings=False
        )
        kwargs["uri"] = uri
        kwargs["api"] = api
        kwargs["resource_args"]["sagemaker"].pop("RoleArn", None)

        with pytest.raises(LaunchError) as e_info:
            launch.run(**kwargs)
        assert (
            str(e_info.value)
            == "AWS sagemaker require a string RoleArn set this by adding a `RoleArn` key to the sagemaker"
            "field of resource_args"
        )
