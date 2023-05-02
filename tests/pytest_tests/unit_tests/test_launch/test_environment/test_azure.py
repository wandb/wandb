from wandb.sdk.launch.environment.azure_environment import AzureEnvironment


def test_azure_environment():
    """Test AzureEnvironment class."""
    config = {
        "type": "azure",
        "storage_account": "wandbbendev8405654764",
        "storage_container": "build-contexts",
    }
    env = AzureEnvironment.from_config(config)


test_azure_environment()
