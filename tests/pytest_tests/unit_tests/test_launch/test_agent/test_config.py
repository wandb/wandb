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
    monkeypatch.setattr(
        "wandb.sdk.launch._launch.LaunchAgent2", lambda *args, **kwargs: MockAgent
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "config, use_agent2, error",
    [
        # Valid configs
        (
            {
                "entity": "test-entity",
                "project": "test-project",
            },
            False,
            False,
        ),
        (
            {
                "entity": "test-entity",
                "project": "test-project",
                "queues": ["test-queue"],
            },
            False,
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
            False,
        ),
        (
            {
                "entity": "test-entity",
                "project": "test-project",
            },
            False,
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
            False,
            True,
        ),
        # Launch Agent 2
        (
            {
                "entity": "test-entity",
                "project": "test-project",
                "queues": ["test-queue"],
            },
            True,
            False,
        ),
    ],
)
def test_create_and_run_agent(config, use_agent2, error, mock_agent):
    if error:
        with pytest.raises(LaunchError):
            create_and_run_agent(MagicMock(), config, use_launch_agent2=use_agent2)
    else:
        create_and_run_agent(MagicMock(), config, use_launch_agent2=use_agent2)
