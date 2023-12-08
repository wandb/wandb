from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError
from wandb.sdk.launch._launch import create_and_run_agent


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
                    type: "ecr",
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
    ],
)
def test_create_and_run_agent(config, error, mock_agent):
    if error:
        with pytest.raises(ValidationError):
            create_and_run_agent(MagicMock(), config)
    else:
        create_and_run_agent(MagicMock(), config)
