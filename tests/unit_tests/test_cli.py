import datetime
import netrc
import os
import traceback

import pytest
import wandb
from wandb.apis.internal import InternalApi
from wandb.cli import cli


@pytest.fixture
def empty_netrc(monkeypatch):
    class FakeNet:
        @property
        def hosts(self):
            return {"api.wandb.ai": None}

    monkeypatch.setattr(netrc, "netrc", lambda *args: FakeNet())


@pytest.mark.skip(reason="Currently dont have on in cling")
def test_enable_on(runner, git_repo):
    with runner.isolated_filesystem():
        with open("wandb/settings", "w") as f:
            f.write("[default]\nproject=rad")
        result = runner.invoke(cli.on)
        print(result.output)
        print(result.exception)
        print(traceback.print_tb(result.exc_info[2]))
        assert "W&B enabled" in str(result.output)
        assert result.exit_code == 0


@pytest.mark.skip(reason="Currently dont have off in cling")
def test_enable_off(runner, git_repo):
    with runner.isolated_filesystem():
        with open("wandb/settings", "w") as f:
            f.write("[default]\nproject=rad")
        result = runner.invoke(cli.off)
        print(result.output)
        print(result.exception)
        print(traceback.print_tb(result.exc_info[2]))
        assert "W&B disabled" in str(result.output)
        assert "disabled" in open("wandb/settings").read()
        assert result.exit_code == 0


def test_no_project_bad_command(runner):
    with runner.isolated_filesystem():
        result = runner.invoke(cli.cli, ["fsd"])
        print(result.output)
        print(result.exception)
        print(traceback.print_tb(result.exc_info[2]))
        assert "No such command" in result.output
        assert result.exit_code == 2


def test_login_key_arg(runner, dummy_api_key):
    with runner.isolated_filesystem():
        # If the test was run from a directory containing .wandb, then __stage_dir__
        # was '.wandb' when imported by api.py, reload to fix. UGH!
        # reload(wandb)
        result = runner.invoke(cli.login, [dummy_api_key])
        print("Output: ", result.output)
        print("Exception: ", result.exception)
        print("Traceback: ", traceback.print_tb(result.exc_info[2]))
        assert result.exit_code == 0
        with open("netrc") as f:
            generated_netrc = f.read()
        assert dummy_api_key in generated_netrc


def test_login_host_trailing_slash_fix_invalid(runner, dummy_api_key, local_settings):
    with runner.isolated_filesystem():
        with open("netrc", "w") as f:
            f.write(f"machine \n  login user\npassword {dummy_api_key}")
        result = runner.invoke(
            cli.login, ["--host", "https://google.com/", dummy_api_key]
        )
        assert result.exit_code == 0
        with open("netrc") as f:
            generated_netrc = f.read()
        assert generated_netrc == (
            "machine google.com\n"
            "  login user\n"
            "  password {}\n".format(dummy_api_key)
        )


@pytest.mark.parametrize(
    "host, error",
    [
        ("https://app.wandb.ai", "did you mean https://api.wandb.ai"),
        ("ftp://google.com", "URL must start with `http(s)://`"),
    ],
)
def test_login_bad_host(runner, host, error, local_settings):
    with runner.isolated_filesystem():
        result = runner.invoke(cli.login, ["--host", host])
        assert error in result.output
        assert result.exit_code != 0


def test_login_onprem_key_arg(runner, dummy_api_key):
    with runner.isolated_filesystem():
        onprem_key = "test-" + dummy_api_key
        # with runner.isolated_filesystem():
        result = runner.invoke(cli.login, [onprem_key])
        print("Output: ", result.output)
        print("Exception: ", result.exception)
        print("Traceback: ", traceback.print_tb(result.exc_info[2]))
        assert result.exit_code == 0
        with open("netrc") as f:
            generated_netrc = f.read()
        assert onprem_key in generated_netrc


def test_login_invalid_key_arg(runner, dummy_api_key):
    with runner.isolated_filesystem():
        invalid_key = "test--" + dummy_api_key
        result = runner.invoke(cli.login, [invalid_key])
        assert "API key must be 40 characters long, yours was" in str(result)
        assert result.exit_code == 1


@pytest.mark.skip(reason="Just need to make the mocking work correctly")
def test_login_anonymously(runner, dummy_api_key, monkeypatch, empty_netrc):
    with runner.isolated_filesystem():
        api = InternalApi()
        monkeypatch.setattr(cli, "api", api)
        monkeypatch.setattr(
            wandb.sdk.internal.internal_api.Api,
            "create_anonymous_api_key",
            lambda *args, **kwargs: dummy_api_key,
        )
        result = runner.invoke(cli.login, ["--anonymously"])
        print("Output: ", result.output)
        print("Exception: ", result.exception)
        print("Traceback: ", traceback.print_tb(result.exc_info[2]))
        assert result.exit_code == 0
        with open("netrc") as f:
            generated_netrc = f.read()
        assert dummy_api_key in generated_netrc


def test_sync_gc(runner):
    with runner.isolated_filesystem():
        if not os.path.isdir("wandb"):
            os.mkdir("wandb")
        d1 = datetime.datetime.now()
        d2 = d1 - datetime.timedelta(hours=3)
        run1 = d1.strftime("run-%Y%m%d_%H%M%S-abcd")
        run2 = d2.strftime("run-%Y%m%d_%H%M%S-efgh")
        run1_dir = os.path.join("wandb", run1)
        run2_dir = os.path.join("wandb", run2)
        os.mkdir(run1_dir)
        with open(os.path.join(run1_dir, "run-abcd.wandb"), "w") as f:
            f.write("")
        with open(os.path.join(run1_dir, "run-abcd.wandb.synced"), "w") as f:
            f.write("")
        os.mkdir(run2_dir)
        with open(os.path.join(run2_dir, "run-efgh.wandb"), "w") as f:
            f.write("")
        with open(os.path.join(run2_dir, "run-efgh.wandb.synced"), "w") as f:
            f.write("")
        assert (
            runner.invoke(
                cli.sync, ["--clean", "--clean-old-hours", "2"], input="y\n"
            ).exit_code
        ) == 0

        assert os.path.exists(run1_dir)
        assert not os.path.exists(run2_dir)
        assert (
            runner.invoke(
                cli.sync, ["--clean", "--clean-old-hours", "0"], input="y\n"
            ).exit_code
            == 0
        )
        assert not os.path.exists(run1_dir)


def test_cli_login_reprompts_when_no_key_specified(runner, mocker, dummy_api_key):
    with runner.isolated_filesystem():
        mocker.patch("wandb.wandb_lib.apikey.getpass", input)
        # this first gives login an empty API key, which should cause
        # it to re-prompt.  this is what we are testing.  we then give
        # it a valid API key (the dummy API key with a different final
        # letter to check that our monkeypatch input is working as
        # expected) to terminate the prompt finally we grep for the
        # Error: No API key specified to assert that the re-prompt
        # happened
        result = runner.invoke(cli.login, input=f"\n{dummy_api_key[:-1]}q\n")
        print(f"DEBUG(login) out = {result.output}")
        print(f"DEBUG(login) exc = {result.exception}")
        print(f"DEBUG(login) tb = {traceback.print_tb(result.exc_info[2])}")
        with open("netrc") as f:
            print(f.read())
        assert "ERROR No API key specified." in result.output
