import platform
from unittest import mock

import pytest
import wandb
from wandb.docker import is_buildx_installed


@pytest.fixture
def mock_shell():
    with mock.patch("wandb.docker.shell") as mock_shell:
        mock_shell.return_value = None
        yield mock_shell


@pytest.mark.skipif(
    platform.system() == "Windows" or platform.system() == "Darwin",
    reason="this test fails incorrectly on CI for Windows and MacOS",
)
@pytest.mark.usefixtures("mock_shell")
def test_buildx_not_installed(runner):
    with runner.isolated_filesystem():
        assert is_buildx_installed() is False


@pytest.mark.parametrize(
    "platform,adds_load_arg",
    [(None, True), ("linux/amd64", True), ("linux/amd64,linux/arm664", False)],
)
def test_buildx_load_platform(platform, adds_load_arg, runner, mocker):
    mocker.patch(wandb.docker.is_buildx_installed, lambda: True)
    mocker.patch(wandb.docker.run_command_live_output, lambda x: x)
    with runner.isolated_filesystem():
        args = wandb.docker.build(["test"], "./Dockerfile", ".", platform)
        if adds_load_arg:
            assert "--load" in args
        else:
            assert "--load" not in args
