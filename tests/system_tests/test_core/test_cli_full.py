import netrc
import os
from unittest import mock

import pytest
import wandb
import wandb.errors.term
from wandb.cli import cli
from wandb.sdk import wandb_setup


@pytest.fixture
def empty_netrc(monkeypatch):
    class FakeNet:
        @property
        def hosts(self):
            return {"api.wandb.ai": None}

    monkeypatch.setattr(netrc, "netrc", lambda *args: FakeNet())


@pytest.mark.xfail(reason="This test is flakey on CI")
def test_init_reinit(runner, empty_netrc, user):
    with (
        runner.isolated_filesystem(),
        mock.patch("wandb.sdk.lib.apikey.len", return_value=40),
    ):
        result = runner.invoke(cli.login, [user])
        result = runner.invoke(cli.init, input="y\n\n\n")
        assert result.exit_code == 0
        with open("netrc") as f:
            generated_netrc = f.read()
        with open("wandb/settings") as f:
            generated_wandb = f.read()
        assert user in generated_netrc
        assert user in generated_wandb


@pytest.mark.xfail(reason="This test is flakey on CI")
def test_init_add_login(runner, empty_netrc, user):
    with (
        runner.isolated_filesystem(),
        mock.patch("wandb.sdk.lib.apikey.len", return_value=40),
    ):
        with open("netrc", "w") as f:
            f.write("previous config")
        result = runner.invoke(cli.login, [user])
        result = runner.invoke(cli.init, input=f"y\n{user}\nvanpelt\n")
        assert result.exit_code == 0
        with open("netrc") as f:
            generated_netrc = f.read()
        with open("wandb/settings") as f:
            generated_wandb = f.read()
        assert user in generated_netrc
        assert user in generated_wandb


@pytest.mark.xfail(reason="This test is flakey on CI")
def test_init_existing_login(runner, user):
    with runner.isolated_filesystem():
        with open("netrc", "w") as f:
            f.write(f"machine localhost\n\tlogin {user}\tpassword {user}")
        result = runner.invoke(cli.init, input="y\nvanpelt\nfoo\n")
        assert result.exit_code == 0
        with open("wandb/settings") as f:
            generated_wandb = f.read()
        assert user in generated_wandb
        assert "This directory is configured" in result.output


@pytest.mark.xfail(reason="This test is flakey on CI")
def test_pull(runner, user):
    with runner.isolated_filesystem():
        project_name = "test_pull"
        file_name = "weights.h5"
        with wandb.init(project=project_name) as run:
            with open(file_name, "w") as f:
                f.write("WEIGHTS")
            run.save(file_name)

        # delete the file so that we can pull it and check that it is there
        os.remove(file_name)

        result = runner.invoke(cli.pull, [run.id, "--project", project_name])
        assert result.exit_code == 0
        assert f"Downloading: {project_name}/{run.id}" in result.output
        assert os.path.isfile(file_name)
        assert f"File {file_name}" in result.output


def test_cli_offline(user, runner):
    with runner.isolated_filesystem():
        result = runner.invoke(cli.offline)
        assert result.exit_code == 0
        wandb_setup.singleton().settings.update_from_system_settings()

        with wandb.init() as run:
            assert run.settings._offline
            assert run.settings.mode == "offline"
