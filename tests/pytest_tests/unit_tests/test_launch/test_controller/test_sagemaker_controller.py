from unittest.mock import MagicMock

import pytest
from wandb.sdk.launch.agent2.controllers.sagemaker import SageMakerManager


@pytest.fixture
def sagemaker_container_manager(controller_config, jobset):
    return SageMakerManager(
        controller_config, jobset, MagicMock(), MagicMock(), MagicMock(), 1
    )


@pytest.mark.parametrize(
    "resource_args, expected",
    [
        ({}, None),
        (
            {"sagemaker": {}},
            [{"Key": "_wandb-jobset", "Value": "ba4d5192668fbae393dc7415dbb83129"}],
        ),
        (
            {"sagemaker": {"Tags": [{"Key": "BLAH", "Value": "test-label"}]}},
            [
                {"Key": "_wandb-jobset", "Value": "ba4d5192668fbae393dc7415dbb83129"},
                {"Key": "BLAH", "Value": "test-label"},
            ],
        ),
    ],
)
def test_label_job(resource_args, expected, sagemaker_container_manager):
    project = MagicMock()
    project.resource_args = resource_args
    sagemaker_container_manager.label_job(project)
    if expected is not None:
        for tag in expected:
            assert tag in project.resource_args.get("sagemaker", {}).get("Tags")
    else:
        assert project.resource_args.get("sagemaker", {}).get("Tags") == expected
