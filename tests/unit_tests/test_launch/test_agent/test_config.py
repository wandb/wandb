from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest
import yaml
from wandb.sdk.launch._launch import create_and_run_agent, resolve_agent_config
from wandb.sdk.launch.agent.config import validate_registry_uri
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
            },
            False,
        ),
        (
            {
                "entity": "test-entity",
                "queues": ["test-queue"],
            },
            False,
        ),
        (
            {
                "entity": "test-entity",
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
            },
            False,
        ),
        # Registry type invalid.
        (
            {
                "entity": "test-entity",
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
    ],
)
def test_create_and_run_agent(config, error, mock_agent):
    if error:
        with pytest.raises(LaunchError):
            create_and_run_agent(MagicMock(), config)
    else:
        create_and_run_agent(MagicMock(), config)


@pytest.mark.parametrize(
    "registry_uri, valid",
    [
        # Valid URIs
        ("https://123456789012.dkr.ecr.us-west-2.amazonaws.com/my-repo", True),
        (
            "https://123456789012.dkr.ecr.us-west-2.amazonaws.com/my-repo.withdash-dot/andslash",
            True,
        ),
        ("https://myregistry.azurecr.io/my-repo", True),
        ("https://us-central1-docker.pkg.dev/my-project/my-repo/my-image", True),
        ("https://myregistry.com/my-repo", True),
        # Invalid URIs
        ("https://123456789012.dkr.ecr.us-west-2.amazonaws.com/my-repo:tag", False),
        (
            "https://123456789012.dkr.ecr.us-west-2.amazonaws.com/my-repo.withdash-dot/andslash:tag",
            False,
        ),
        ("https://myregistry.azurecr.io/my-repo:tag", False),
        ("https://us-central1-docker.pkg.dev/my-project/my-repo/my-image:tag", False),
        ("https://us-central1-docker.pkg.dev/my-project/my-repo", False),
    ],
)
def test_validate_registry_uri(registry_uri, valid):
    """Test that we validated the registry URI correctly."""
    if not valid:
        with pytest.raises(ValueError):
            validate_registry_uri(registry_uri)
    else:
        validate_registry_uri(registry_uri)


def test_resolve_agent_config(monkeypatch, runner):
    monkeypatch.setattr(
        "wandb.sdk.launch._launch.LAUNCH_CONFIG_FILE",
        "./config/wandb/launch-config.yaml",
    )
    monkeypatch.setenv("WANDB_ENTITY", "diffentity")
    with runner.isolated_filesystem():
        os.makedirs("./config/wandb")
        with open("./config/wandb/launch-config.yaml", "w") as f:
            yaml.dump(
                {
                    "entity": "different-entity",
                    "max_jobs": 2,
                    "registry": {"url": "test"},
                },
                f,
            )
        config, returned_api = resolve_agent_config(
            entity=None,
            max_jobs=-1,
            queues=["diff-queue"],
            config=None,
            verbosity=None,
        )

        assert config["registry"] == {"url": "test"}
        assert config["entity"] == "diffentity"
        assert config["max_jobs"] == -1
