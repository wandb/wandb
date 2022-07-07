from unittest import mock


import wandb
from wandb.docker import is_buildx_installed

import pytest


@pytest.fixture
def mock_shell():
    with mock.patch("wandb.docker.shell") as mock_shell:
        mock_shell.return_value = None
        yield mock_shell


def test_buildx_not_installed(mock_shell, runner):

    with runner.isolated_filesystem():
        assert is_buildx_installed() is False
    assert wandb.docker._buildx_installed is False
