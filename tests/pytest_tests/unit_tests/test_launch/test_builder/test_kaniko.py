from unittest.mock import MagicMock

import pytest
from wandb.sdk.launch.builder.kaniko_builder import KanikoBuilder
from wandb.sdk.launch.environment.azure_environment import AzureEnvironment
from wandb.sdk.launch.registry.azure_container_registry import AzureContainerRegistry


class AsyncMock(MagicMock):
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
def azure_container_registry(mocker, azure_environment):
    """Fixture for AzureContainerRegistry class."""
    mocker.patch(
        "wandb.sdk.launch.environment.azure_environment.DefaultAzureCredential",
        MagicMock(),
    )
    config = {
        "uri": "https://registry.azurecr.io/test-repo",
    }
    return AzureContainerRegistry.from_config(config, azure_environment)


@pytest.mark.asyncio
async def test_kaniko_azure(azure_container_registry):
    """Test that the kaniko builder correctly constructs the job spec for Azure."""
    builder = KanikoBuilder(
        environment=azure_container_registry.environment,
        registry=azure_container_registry,
        build_job_name="test",
        build_context_store="https://account.blob.core.windows.net/container/blob",
    )
    core_client = MagicMock()
    core_client.read_namespaced_secret = AsyncMock(return_value=None)
    job = await builder._create_kaniko_job(
        "test-job",
        "https://registry.azurecr.io/test-repo",
        "12345678",
        "https://account.blob.core.windows.net/container/blob",
        core_client,
    )
    # Check that the AZURE_STORAGE_ACCESS_KEY env var is set correctly.
    assert any(
        env_var.name == "AZURE_STORAGE_ACCESS_KEY"
        for env_var in job.spec.template.spec.containers[0].env
    )
    # Check the dockerconfig is mounted and the correct secret + value are used.
    assert any(
        volume.name == "docker-config" for volume in job.spec.template.spec.volumes
    )
    assert any(
        volume_mount.name == "docker-config"
        for volume_mount in job.spec.template.spec.containers[0].volume_mounts
    )
