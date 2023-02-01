from wandb.sdk.launch.environment.aws_environment import AwsEnvironment, AwsConfig
from wandb.errors import LaunchError
import pytest


def test_aws_config_from_dict():
    """Test AwsConfig.from_dict.

    AwsConfig.from_dict is very simple, these test cases simply verify that
    the right exceptions are raised when the dictionary is invalid.
    """
    # Test valid config.
    config = {
        "region": "us-west-2",
        "profile": "test_profile",
        "kubernetes_secret": "test_secret",
    }
    aws_config = AwsConfig.from_dict(config)
    assert aws_config.region == "us-west-2"
    assert aws_config.profile == "test_profile"

    # Test empty config.
    with pytest.raises(LaunchError):
        AwsConfig.from_dict({})

    # Test missing required keys.
    with pytest.raises(LaunchError):
        AwsConfig.from_dict({"profile": "test"})

    # Test unknown keys.
    with pytest.raises(LaunchError):
        AwsConfig.from_dict({"region": "us-west-2", "unknown_key": "test"})

    # Test missing required keys and unknown keys.
    with pytest.raises(LaunchError):
        AwsConfig.from_dict({"unknown_key": "test"})
