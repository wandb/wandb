from unittest.mock import MagicMock

import pytest
from wandb.sdk.launch.environment.azure_environment import AzureEnvironment
from wandb.sdk.launch.registry.azure_container_registry import (
    AzureContainerRegistry,
    ResourceNotFoundError,
)


def test_acr_from_config(mocker):
    """Test AzureContainerRegistry class."""
    mocker.patch(
        "wandb.sdk.launch.environment.azure_environment.DefaultAzureCredential",
        MagicMock(),
    )
    mocker.patch(
        "wandb.sdk.launch.registry.azure_container_registry.AzureContainerRegistry.verify",
        MagicMock(),
    )
    config = {"uri": "test"}
    acr = AzureContainerRegistry.from_config(config, AzureEnvironment.from_config({}))
    assert acr.uri == "test"


@pytest.mark.asyncio
async def test_acr_get_repo_uri(mocker):
    """Test AzureContainerRegistry class."""
    mocker.patch(
        "wandb.sdk.launch.environment.azure_environment.DefaultAzureCredential",
        MagicMock(),
    )
    mocker.patch(
        "wandb.sdk.launch.registry.azure_container_registry.AzureContainerRegistry.verify",
        MagicMock(),
    )
    config = {"uri": "test"}
    registry = AzureContainerRegistry.from_config(
        config, AzureEnvironment.from_config({})
    )
    assert await registry.get_repo_uri() == "test"


@pytest.mark.asyncio
async def test_acr_check_image_exists(mocker):
    """Test AzureContainerRegistry class."""
    mocker.patch(
        "wandb.sdk.launch.environment.azure_environment.DefaultAzureCredential",
        MagicMock(),
    )
    mocker.patch(
        "wandb.sdk.launch.registry.azure_container_registry.AzureContainerRegistry.verify",
        MagicMock(),
    )

    # Make the mock client return a digest when get_manifest_properties is called and
    # check that the method returns True.
    mock_client = MagicMock()
    mock_client.get_manifest_properties.return_value = {"digest": "test"}
    mocker.patch(
        "wandb.sdk.launch.registry.azure_container_registry.ContainerRegistryClient",
        MagicMock(return_value=mock_client),
    )
    config = {"uri": "test"}
    registry = AzureContainerRegistry.from_config(
        config, AzureEnvironment.from_config({})
    )
    assert await registry.check_image_exists("test.azurecr.io/launch-images:tag")

    # Make the mock client raise an error when get_manifest_properties is called and
    # check that the method returns False.
    mock_client.get_manifest_properties.side_effect = ResourceNotFoundError()
    mocker.patch(
        "wandb.sdk.launch.registry.azure_container_registry.ContainerRegistryClient",
        MagicMock(return_value=mock_client),
    )
    assert not await registry.check_image_exists(
        "https://test.azurecr.io/launch-images:tag"
    )


def test_acr_registry_name(mocker):
    """Test if repository name is parsed correctly."""
    mocker.patch(
        "wandb.sdk.launch.environment.azure_environment.DefaultAzureCredential",
        MagicMock(),
    )
    config = {"uri": "https://test.azurecr.io/repository"}
    registry = AzureContainerRegistry.from_config(
        config, AzureEnvironment.from_config({})
    )
    assert registry.registry_name == "test"
    # Same thing but without https
    config = {"uri": "test.azurecr.io/repository"}
    registry = AzureContainerRegistry.from_config(
        config, AzureEnvironment.from_config({})
    )
    assert registry.registry_name == "test"
