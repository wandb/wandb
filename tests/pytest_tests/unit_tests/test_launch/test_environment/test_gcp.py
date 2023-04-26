from unittest.mock import MagicMock

from wandb.sdk.launch.environment.gcp_environment import GcpEnvironment


def test_environment_verify(mocker):
    """Test that the environment is verified correctly."""
    credentials = MagicMock()
    credentials.refresh = MagicMock()
    credentials.valid = True
    mocker.patch(
        "wandb.sdk.launch.environment.gcp_environment.google.auth.default",
        return_value=(credentials, "project"),
    )
    mock_region_client = MagicMock()
    mocker.patch(
        "wandb.sdk.launch.environment.gcp_environment.google.cloud.compute_v1.RegionsClient",
        mock_region_client,
    )
    GcpEnvironment("region")
    mock_region_client.return_value.get.assert_called_once_with(
        project="project", region="region"
    )
