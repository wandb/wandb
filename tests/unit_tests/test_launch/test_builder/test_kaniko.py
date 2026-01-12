from __future__ import annotations

import os
from unittest.mock import MagicMock

import boto3
import kubernetes_asyncio
import pytest
import wandb
from google.cloud import storage
from wandb.sdk.launch._project_spec import EntryPoint, LaunchProject
from wandb.sdk.launch.builder.kaniko_builder import (
    KanikoBuilder,
    _wait_for_completion,
    get_pod_name_safe,
)
from wandb.sdk.launch.environment.aws_environment import AwsEnvironment
from wandb.sdk.launch.environment.azure_environment import AzureEnvironment
from wandb.sdk.launch.registry.anon import AnonynmousRegistry
from wandb.sdk.launch.registry.azure_container_registry import AzureContainerRegistry
from wandb.sdk.launch.registry.elastic_container_registry import (
    ElasticContainerRegistry,
)


class AsyncMock(MagicMock):
    """Mock for async functions."""

    async def __call__(self, *args, **kwargs):
        return super().__call__(*args, **kwargs)


@pytest.fixture
def azure_environment(mocker):
    """Fixture for AzureEnvironment class."""
    mocker.patch(
        "wandb.sdk.launch.environment.azure_environment.DefaultAzureCredential",
        MagicMock(),
    )
    config = {
        "environment": {
            "type": "azure",
        }
    }
    return AzureEnvironment.from_config(config)


@pytest.fixture
def aws_environment(mocker):
    """Fixture for AwsEnvironment class."""
    mocker.patch("wandb.sdk.launch.environment.aws_environment.boto3", MagicMock())
    config = {
        "type": "aws",
        "region": "us-east-1",
    }
    return AwsEnvironment.from_config(config)


@pytest.fixture
def azure_container_registry(mocker, azure_environment):
    """Fixture for AzureContainerRegistry class."""
    mocker.patch(
        "wandb.sdk.launch.environment.azure_environment.DefaultAzureCredential",
        MagicMock(),
    )
    config = {
        "uri": "https://registry.azurecr.io/test-repo",
    }
    return AzureContainerRegistry.from_config(config)


@pytest.fixture
def elastic_container_registry(mocker):
    """Fixture for ElasticContainerRegistry class."""
    config = {
        "uri": "12345678.dkr.ecr.us-east-1.amazonaws.com/test-repo",
    }
    return ElasticContainerRegistry.from_config(config)


@pytest.mark.asyncio
async def test_kaniko_azure(azure_container_registry, azure_environment):
    """Test that the kaniko builder correctly constructs the job spec for Azure."""
    builder = KanikoBuilder(
        environment=azure_environment,
        registry=azure_container_registry,
        build_job_name="test",
        build_context_store="https://account.blob.core.windows.net/container/blob",
    )
    core_client = MagicMock()
    core_client.read_namespaced_secret = AsyncMock(return_value=None)
    api_client = MagicMock()
    job = await builder._create_kaniko_job(
        "test-job",
        "https://registry.azurecr.io/test-repo",
        "12345678",
        "https://account.blob.core.windows.net/container/blob",
        core_client,
        api_client,
    )
    # Check that the AZURE_STORAGE_ACCESS_KEY env var is set correctly.
    assert any(
        env_var["name"] == "AZURE_STORAGE_ACCESS_KEY"
        for env_var in job["spec"]["template"]["spec"]["containers"][0]["env"]
    )
    # Check the dockerconfig is mounted and the correct secret + value are used.
    assert any(
        volume["name"] == "docker-config"
        for volume in job["spec"]["template"]["spec"]["volumes"]
    )
    assert any(
        volume_mount["name"] == "docker-config"
        for volume_mount in job["spec"]["template"]["spec"]["containers"][0][
            "volumeMounts"
        ]
    )


def return_kwargs(**kwargs):
    return kwargs


@pytest.fixture
def mock_kubernetes_clients(monkeypatch):
    mock_config_map = MagicMock()
    mock_config_map.metadata = MagicMock()
    mock_config_map.metadata.name = "test-config-map"
    monkeypatch.setattr(kubernetes_asyncio.client, "V1ConfigMap", mock_config_map)

    mock_batch_client = MagicMock(name="batch-client")
    mock_batch_client.read_name_spaced_job_log = AsyncMock(return_value=MagicMock())
    mock_batch_client.create_namespaced_job = AsyncMock(return_value=MagicMock())
    mock_batch_client.delete_namespaced_job = AsyncMock(return_value=MagicMock())

    mock_core_client = MagicMock(name="core-client")
    mock_core_client.create_namespaced_config_map = AsyncMock(return_value=None)
    mock_core_client.delete_namespaced_config_map = AsyncMock(return_value=None)

    mock_job = MagicMock(name="mock_job")
    mock_job_status = MagicMock()
    mock_job.status = mock_job_status
    # test success is true
    mock_job_status.succeeded = 1
    mock_batch_client.read_namespaced_job_status = AsyncMock(return_value=mock_job)
    monkeypatch.setattr(
        kubernetes_asyncio.client,
        "BatchV1Api",
        MagicMock(return_value=mock_batch_client),
    )
    monkeypatch.setattr(
        kubernetes_asyncio.client, "CoreV1Api", MagicMock(return_value=mock_core_client)
    )
    monkeypatch.setattr(kubernetes_asyncio.client, "V1PodSpec", return_kwargs)
    monkeypatch.setattr(kubernetes_asyncio.client, "V1Volume", return_kwargs)
    monkeypatch.setattr(kubernetes_asyncio.client, "V1JobSpec", return_kwargs)
    monkeypatch.setattr(kubernetes_asyncio.client, "V1Job", return_kwargs)
    monkeypatch.setattr(kubernetes_asyncio.client, "V1PodTemplateSpec", return_kwargs)
    monkeypatch.setattr(kubernetes_asyncio.client, "V1Container", return_kwargs)
    monkeypatch.setattr(kubernetes_asyncio.client, "V1VolumeMount", return_kwargs)
    monkeypatch.setattr(
        kubernetes_asyncio.client, "V1SecretVolumeSource", return_kwargs
    )
    monkeypatch.setattr(
        kubernetes_asyncio.client, "V1ConfigMapVolumeSource", return_kwargs
    )
    monkeypatch.setattr(kubernetes_asyncio.client, "V1ObjectMeta", return_kwargs)
    monkeypatch.setattr(
        kubernetes_asyncio.config, "load_incluster_config", return_kwargs
    )
    yield mock_core_client, mock_batch_client


@pytest.fixture
def mock_v1_object_meta(monkeypatch):
    monkeypatch.setattr(kubernetes_asyncio.client, "V1ObjectMeta", return_kwargs)
    yield return_kwargs


@pytest.fixture
def mock_v1_config_map(monkeypatch):
    monkeypatch.setattr(kubernetes_asyncio.client, "V1ConfigMap", return_kwargs)
    yield return_kwargs


@pytest.fixture
def mock_boto3(monkeypatch):
    monkeypatch.setattr(boto3, "client", MagicMock())


@pytest.fixture
def mock_storage_client(monkeypatch):
    monkeypatch.setattr(storage, "Client", MagicMock())


@pytest.mark.asyncio
async def test_wait_for_completion():
    mock_api_client = MagicMock()
    mock_job = MagicMock()
    mock_job_status = MagicMock()
    mock_job.status = mock_job_status
    # test success is true
    mock_job_status.succeeded = 1
    mock_api_client.read_namespaced_job_status = AsyncMock(return_value=mock_job)
    assert await _wait_for_completion(mock_api_client, "test", 60)

    # test failed is false
    mock_job_status.succeeded = None
    mock_job_status.failed = 1
    assert await _wait_for_completion(mock_api_client, "test", 60) is False

    # test timeout is false
    mock_job_status.failed = None
    assert await _wait_for_completion(mock_api_client, "test", 5) is False


@pytest.mark.asyncio
async def test_create_kaniko_job_static(
    mock_kubernetes_clients, elastic_container_registry, runner
):
    with runner.isolated_filesystem():
        os.makedirs("./test/context/path/", exist_ok=True)
        with open("./test/context/path/Dockerfile.wandb", "wb") as f:
            f.write(b"docker file test contents")
        builder = KanikoBuilder(
            MagicMock(),
            elastic_container_registry,
            build_context_store="s3://test-bucket/test-prefix",
            secret_name="test-secret",
            secret_key="test-key",
            config={
                "spec": {
                    "template": {
                        "spec": {
                            "containers": [
                                {
                                    "args": ["--test-arg=test-value"],
                                    "volumeMounts": [
                                        {
                                            "name": "test-volume",
                                            "mountPath": "/test/path/",
                                        }
                                    ],
                                }
                            ],
                            "volumes": [{"name": "test-volume"}],
                        }
                    }
                }
            },
        )
        job_name = "test_job_name"
        repo_url = "repository-url"
        image_tag = "image_tag:12345678"
        context_path = "./test/context/path/"
        job = await builder._create_kaniko_job(
            job_name,
            repo_url,
            image_tag,
            context_path,
            kubernetes_asyncio.client.CoreV1Api(),
            MagicMock(),
        )

        assert job["metadata"]["name"] == "test_job_name"
        assert job["metadata"]["namespace"] == "wandb"
        assert job["metadata"]["labels"] == {"wandb": "launch"}
        assert (
            job["spec"]["template"]["spec"]["containers"][0]["image"]
            == "gcr.io/kaniko-project/executor:v1.11.0"
        )
        assert job["spec"]["template"]["spec"]["containers"][0]["args"] == [
            f"--context={context_path}",
            "--dockerfile=Dockerfile.wandb",
            f"--destination={image_tag}",
            "--cache=true",
            f"--cache-repo={repo_url}",
            "--snapshot-mode=redo",
            "--compressed-caching=false",
            "--test-arg=test-value",
        ]

        assert job["spec"]["template"]["spec"]["containers"][0]["volumeMounts"] == [
            {
                "name": "test-volume",
                "mountPath": "/test/path/",
            },
            {
                "name": "docker-config",
                "mountPath": "/kaniko/.docker",
            },
            {
                "name": "test-secret",
                "mountPath": "/root/.aws",
                "readOnly": True,
            },
        ]

        assert job["spec"]["template"]["spec"]["volumes"][0] == {"name": "test-volume"}
        assert job["spec"]["template"]["spec"]["volumes"][1] == {
            "name": "docker-config",
            "configMap": {"name": "docker-config-test_job_name"},
        }
        assert job["spec"]["template"]["spec"]["volumes"][2]["name"] == "test-secret"
        assert (
            job["spec"]["template"]["spec"]["volumes"][2]["secret"]["secretName"]
            == "test-secret"
        )
        assert (
            job["spec"]["template"]["spec"]["volumes"][2]["secret"]["items"][0]["key"]
            == "test-key"
        )
        assert (
            job["spec"]["template"]["spec"]["volumes"][2]["secret"]["items"][0]["path"]
            == "credentials"
        )
        assert (
            "mode"
            not in job["spec"]["template"]["spec"]["volumes"][2]["secret"]["items"][0]
        )


@pytest.mark.asyncio
async def test_create_kaniko_job_instance(
    elastic_container_registry, mock_kubernetes_clients, runner
):
    with runner.isolated_filesystem():
        os.makedirs("./test/context/path/", exist_ok=True)
        with open("./test/context/path/Dockerfile.wandb", "wb") as f:
            f.write(b"docker file test contents")
        builder = KanikoBuilder(
            MagicMock(),
            elastic_container_registry,
            build_context_store="s3://test-bucket/test-prefix",
        )
        job_name = "test_job_name"
        repo_url = "12345678.dkr.ecr.us-east-1.amazonaws.com/test-repo"
        image_tag = "image_tag:12345678"
        context_path = "./test/context/path/"
        job = await builder._create_kaniko_job(
            job_name, repo_url, image_tag, context_path, MagicMock(), MagicMock()
        )

        assert job["metadata"]["name"] == "test_job_name"
        assert job["metadata"]["namespace"] == "wandb"
        assert job["metadata"]["labels"] == {"wandb": "launch"}
        assert (
            job["spec"]["template"]["spec"]["containers"][0]["image"]
            == "gcr.io/kaniko-project/executor:v1.11.0"
        )
        assert job["spec"]["template"]["spec"]["containers"][0]["args"] == [
            f"--context={context_path}",
            "--dockerfile=Dockerfile.wandb",
            f"--destination={image_tag}",
            "--cache=true",
            f"--cache-repo={repo_url}",
            "--snapshot-mode=redo",
            "--compressed-caching=false",
        ]

        assert job["spec"]["template"]["spec"]["containers"][0]["volumeMounts"] == []
        assert job["spec"]["template"]["spec"]["volumes"] == []


@pytest.mark.asyncio
async def test_create_kaniko_job_pvc_dockerconfig(
    mock_kubernetes_clients, runner, mocker
):
    """Test that the kaniko builder mounts pvc and dockerconfig correctly."""
    mocker.patch("wandb.sdk.launch.builder.kaniko_builder.PVC_NAME", "test-pvc")
    mocker.patch(
        "wandb.sdk.launch.builder.kaniko_builder.PVC_MOUNT_PATH", "/mnt/test-pvc"
    )
    mocker.patch(
        "wandb.sdk.launch.builder.kaniko_builder.DOCKER_CONFIG_SECRET", "test-secret"
    )

    with runner.isolated_filesystem():
        os.makedirs("./test/context/path/", exist_ok=True)
        with open("./test/context/path/Dockerfile.wandb", "wb") as f:
            f.write(b"docker file test contents")
        job_name = "test_job_name"
        repo_url = "myspace.com/test-repo"
        image_tag = "12345678"
        context_path = "./test/context/path/"
        builder = KanikoBuilder(
            MagicMock(),
            AnonynmousRegistry(repo_url),
        )
        job = await builder._create_kaniko_job(
            job_name, repo_url, image_tag, context_path, MagicMock(), MagicMock()
        )

        assert job["metadata"]["name"] == "test_job_name"
        assert job["metadata"]["namespace"] == "wandb"
        assert job["metadata"]["labels"] == {"wandb": "launch"}
        assert (
            job["spec"]["template"]["spec"]["containers"][0]["image"]
            == "gcr.io/kaniko-project/executor:v1.11.0"
        )
        assert job["spec"]["template"]["spec"]["containers"][0]["args"] == [
            f"--context={context_path}",
            "--dockerfile=Dockerfile.wandb",
            f"--destination={image_tag}",
            "--cache=true",
            f"--cache-repo={repo_url}",
            "--snapshot-mode=redo",
            "--compressed-caching=false",
        ]

    assert job["spec"]["template"]["spec"]["containers"][0]["volumeMounts"] == [
        {
            "name": "kaniko-pvc",
            "mountPath": "/context",
        },
        {
            "name": "kaniko-docker-config",
            "mountPath": "/kaniko/.docker",
        },
    ]

    pvc_volume = job["spec"]["template"]["spec"]["volumes"][0]
    dockerconfig_volume = job["spec"]["template"]["spec"]["volumes"][1]

    assert pvc_volume["name"] == "kaniko-pvc"
    assert pvc_volume["persistentVolumeClaim"]["claimName"] == "test-pvc"
    assert "readOnly" not in pvc_volume["persistentVolumeClaim"]

    assert dockerconfig_volume["name"] == "kaniko-docker-config"
    assert dockerconfig_volume["secret"]["secretName"] == "test-secret"
    assert dockerconfig_volume["secret"]["items"][0]["key"] == ".dockerconfigjson"
    assert dockerconfig_volume["secret"]["items"][0]["path"] == "config.json"


@pytest.mark.asyncio
async def test_build_image_success(
    monkeypatch,
    mock_kubernetes_clients,
    aws_environment,
    elastic_container_registry,
    runner,
    mock_boto3,
    test_settings,
    capsys,
    tmp_path,
):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings(), load_settings=False
    )
    monkeypatch.setattr(
        wandb.sdk.launch._project_spec.LaunchProject, "build_required", lambda x: True
    )
    with runner.isolated_filesystem():
        os.makedirs("./test/context/path/", exist_ok=True)
        with open("./test/context/path/Dockerfile.wandb", "wb") as f:
            f.write(b"docker file test contents")
        mock_job = MagicMock(name="mock_job")
        mock_job.status.succeeded = 1
        builder = KanikoBuilder(
            aws_environment,
            elastic_container_registry,
            build_context_store="s3://test-bucket/test-prefix",
        )
        job_name = "mock_server_entity/test/job-artifact"
        job_version = 0
        kwargs = {
            "uri": None,
            "job": f"{job_name}:v{job_version}",
            "api": api,
            "launch_spec": {},
            "target_entity": "mock_server_entity",
            "target_project": "test",
            "name": None,
            "docker_config": {},
            "git_info": {},
            "overrides": {"entry_point": ["python", "main.py"]},
            "resource": "kubernetes",
            "resource_args": {},
            "run_id": None,
        }
        project = LaunchProject(**kwargs)
        mock_artifact = MagicMock()
        mock_artifact.name = job_name
        mock_artifact.version = job_version
        project._job_artifact = mock_artifact
        entry_point = EntryPoint("main.py", ["python", "main.py"])
        project.set_job_entry_point(entry_point.command)
        image_uri = await builder.build_image(project, entry_point)
        assert (
            "Created kaniko job wandb-launch-container-build-"
            in capsys.readouterr().err
        )
        assert "12345678.dkr.ecr.us-east-1.amazonaws.com/test-repo" in image_uri


def test_kaniko_builder_from_config(aws_environment, elastic_container_registry):
    """Test that the kaniko builder correctly constructs the job spec for Azure."""
    config = {
        "type": "kaniko",
        "build-context-store": "s3://test-bucket/test-prefix",
        "destination": "12345678.dkr.ecr.us-east-1.amazonaws.com/test-repo",
    }
    builder = KanikoBuilder.from_config(
        config, aws_environment, elastic_container_registry
    )
    assert builder.build_context_store == "s3://test-bucket/test-prefix"


def test_get_pod_name():
    job = kubernetes_asyncio.client.V1Job(
        api_version="batch/v1",
        kind="Job",
        metadata=kubernetes_asyncio.client.V1ObjectMeta(name="test-job"),
        spec=kubernetes_asyncio.client.V1JobSpec(
            template=kubernetes_asyncio.client.V1PodTemplateSpec(
                metadata=kubernetes_asyncio.client.V1ObjectMeta(name="test-pod-name"),
            )
        ),
    )
    assert get_pod_name_safe(job) == "test-pod-name"
    job = kubernetes_asyncio.client.V1Job(
        api_version="batch/v1",
        kind="Job",
    )
    assert get_pod_name_safe(job) is None
