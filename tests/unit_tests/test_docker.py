from unittest import mock

import pytest
import wandb
from wandb.docker import is_buildx_installed


@pytest.fixture
def mock_shell():
    with mock.patch("wandb.docker.shell") as mock_shell:
        mock_shell.return_value = None
        yield mock_shell


@pytest.mark.usefixtures("mock_shell")
def test_buildx_not_installed():

    assert is_buildx_installed() is False
    assert wandb.docker._buildx_installed is False
