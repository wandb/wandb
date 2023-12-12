from unittest.mock import MagicMock

import pytest
from wandb.sdk.launch._launch import create_and_run_agent
from wandb.sdk.launch.errors import LaunchError


class MockAgent:
    def __init__(self, api, config):
        self.api = api
        self.config = config

    async def loop(*args, **kwargs):
        pass


@pytest.fixture
def mock_agent(monkeypatch):
    monkeypatch.setattr(
        "wandb.sdk.launch._launch.LaunchAgent", lambda *args, **kwargs: MockAgent
    )


@pytest.mark.parametrize(
    "config, error",
    [
        # Valid configs
        (
            {
                "entity": "test-entity",
                "project": "test-project",
            },
            False,
        ),
        (
            {
                "entity": "test-entity",
                "project": "test-project",
                "queues": ["test-queue"],
            },
            False,
        ),
        (
            {
                "entity": "test-entity",
                "project": "test-project",
                "queues": ["test-queue"],
                "builder": {
                    "type": "docker",
                },
                "registry": {
                    "type": "ecr",
                },
            },
            False,
        ),
        (
            {
                "entity": "test-entity",
                "project": "test-project",
            },
            False,
        ),
        # Registry type invalid.
        (
            {
                "entity": "test-entity",
                "project": "test-project",
                "queues": ["test-queue"],
                "builder": {
                    "type": "docker",
                },
                "registry": {
                    "type": "ecrr",
                },
            },
            True,
        ),
        # Builder type set to kaniko but build-context-store not set.
        (
            {
                "entity": "test-entity",
                "project": "test-project",
                "queues": ["test-queue"],
                "builder": {
                    "type": "kaniko",
                },
                "registry": {
                    "type": "ecr",
                },
            },
            True,
        ),
    ],
)
def test_create_and_run_agent(config, error, mock_agent):
    if error:
        with pytest.raises(LaunchError):
            create_and_run_agent(MagicMock(), config)
    else:
        create_and_run_agent(MagicMock(), config)
