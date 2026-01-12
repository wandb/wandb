"""Tests for the sagemaker runner."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from wandb.sdk.launch.runner.sagemaker_runner import launch_sagemaker_job


@pytest.fixture
def mock_launch_project():
    return MagicMock()


@pytest.fixture
def mock_sagemaker_client():
    mock_client = MagicMock()
    mock_client.create_training_job.return_value = {
        "TrainingJobArn": "arn:aws:sagemaker:us-west-2:123456789012:training-job/my-training-job"
    }
    return mock_client


@pytest.fixture
def mock_logs_client():
    mock_client = MagicMock()
    mock_client.describe_log_streams.return_value = {
        "logStreams": [
            {"logStreamName": "my-training-job"},
        ]
    }
    mock_client.get_log_events.return_value = {
        "events": [
            {"message": "Hello, world!", "timestamp": 1234567890},
            {"message": "Goodbye, world!", "timestamp": 1234567891},
        ]
    }
    mock_client.exceptions.ResourceNotFoundException = IndexError
    return mock_client


@pytest.mark.asyncio
async def test_launch_sagemaker_job(
    mock_launch_project,
    mock_sagemaker_client,
    mock_logs_client,
):
    sagemaker_args = {
        "image": "123456789012.dkr.ecr.us-west-2.amazonaws.com/sagemaker-training-containers/my-training-job",
        "instance_type": "ml.m5.xlarge",
        "instance_count": 1,
        "hyperparameters": {
            "epochs": 10,
            "batch_size": 32,
        },
    }

    run = await launch_sagemaker_job(
        mock_launch_project,
        sagemaker_args,
        mock_sagemaker_client,
        mock_logs_client,
    )
    logs = await run.get_logs()

    assert logs == "1234567890:Hello, world!\n1234567891:Goodbye, world!"
    assert mock_sagemaker_client.create_training_job.call_args[1] == sagemaker_args
