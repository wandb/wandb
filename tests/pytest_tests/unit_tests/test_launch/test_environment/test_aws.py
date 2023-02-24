from wandb.sdk.launch.environment.aws_environment import AwsEnvironment
from wandb.errors import LaunchError
import pytest

from unittest.mock import MagicMock


def test_create_aws_environment():
    """Test AwsEnvironment"""
    env = AwsEnvironment(region="us-west-2")
    env
