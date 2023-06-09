from unittest.mock import MagicMock

from wandb.sdk.launch.environment.azure_environment import AzureEnvironment
from wandb.sdk.launch.registry.azure_container_registry import AzureContainerRegistry


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
    AzureContainerRegistry.from_config(config, AzureEnvironment.from_config({}))


def test_acr_get_repo_uri(mocker):
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
    assert registry.get_repo_uri() == "test"


def test_acr_check_image_exists(mocker):
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
    assert not registry.check_image_exists("test")


def test_acr_registry_name(mocker):
    """Test if repository name is parsed correctly."""
    mocker.patch(
        "wandb.sdk.launch.environment.azure_environment.DefaultAzureCredential",
        MagicMock(),
    )
    config = {"uri": "test.azurecr.io/repository"}
    registry = AzureContainerRegistry.from_config(
        config, AzureEnvironment.from_config({})
    )
    assert registry.registry_name == "test"
