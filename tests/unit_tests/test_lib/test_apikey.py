import os
import stat
from unittest import mock

import pytest
from wandb import wandb, wandb_lib
from wandb.sdk.lib.apikey import _api_key_prompt_str


def test_write_netrc(mock_wandb_log):
    api_key = "X" * 40
    wandb_lib.apikey.write_netrc("http://localhost", "vanpelt", api_key)
    assert mock_wandb_log.logged("No netrc file found, creating one.")
    with open(wandb_lib.apikey.get_netrc_file_path()) as f:
        assert f.read() == (
            f"machine localhost\n  login vanpelt\n  password {api_key}\n"
        )


def test_write_netrc_update_existing(tmp_path):
    settings = wandb.Settings(base_url="http://localhost")
    old_api_key = "X" * 40
    netrc_path = str(tmp_path / "netrc")
    os.environ["NETRC"] = netrc_path
    with open(netrc_path, "w") as f:
        f.writelines(
            [
                "machine otherhost\n  login other-user\n  password password123\n",
                "machine localhost\n  login random-user\n  password " + old_api_key,
            ]
        )
    os.chmod(netrc_path, stat.S_IRUSR | stat.S_IWUSR)
    assert wandb_lib.apikey.api_key(settings) == old_api_key

    new_api_key = "Y" * 40
    wandb_lib.apikey.write_netrc("http://localhost", "random-user", new_api_key)
    assert wandb_lib.apikey.api_key(settings) == new_api_key
    with open(netrc_path) as f:
        assert f.read() == (
            "machine otherhost\n  login other-user\n  password password123\n"
            f"machine localhost\n  login random-user\n  password {new_api_key}\n"
        )


@pytest.mark.parametrize(
    "read_permission, write_permission",
    [
        (False, True),
        (True, False),
        (False, False),
    ],
    ids=["no_read", "no_write", "no_read_no_write"],
)
def test_netrc_permission_errors(
    tmp_path,
    mock_wandb_log,
    read_permission,
    write_permission,
):
    netrc_path = str(tmp_path / "netrc")
    os.environ["NETRC"] = netrc_path
    api_key = "X" * 40
    with mock.patch(
        "wandb.sdk.lib.apikey.check_netrc_access",
        return_value=wandb_lib.apikey._NetrcPermissions(
            exists=True,
            read_access=read_permission,
            write_access=write_permission,
        ),
    ):
        with pytest.raises(wandb_lib.apikey.WriteNetrcError) as expected_error:
            wandb_lib.apikey.write_netrc("http://localhost", "random-user", api_key)
        assert str(expected_error.value) == (
            f"Cannot access {netrc_path}. In order to persist your API key, "
            "grant read and write permissions for your user to the file "
            'or specify a different file with the environment variable "NETRC=<new_netrc_path>".'
        )


def test_stat_netrc_permission_oserror(tmp_path, mock_wandb_log):
    netrc_path = str(tmp_path / "netrc")
    os.environ["NETRC"] = netrc_path
    with open(netrc_path, "w") as f:
        f.write("")
    os.chmod(netrc_path, stat.S_IRUSR | stat.S_IWUSR)
    api_key = "X" * 40

    with mock.patch(
        "os.stat",
        side_effect=OSError,
    ):
        with pytest.raises(wandb_lib.apikey.WriteNetrcError) as expected_error:
            wandb_lib.apikey.write_netrc("http://localhost", "random-user", api_key)
            assert (
                str(expected_error.value)
                == f"Unable to read permissions for {netrc_path}"
            )


def test_write_netrc_permission_oserror(tmp_path, mock_wandb_log):
    netrc_path = str(tmp_path / "netrc")
    os.environ["NETRC"] = netrc_path
    with open(netrc_path, "w") as f:
        f.write("")
    os.chmod(netrc_path, stat.S_IRUSR | stat.S_IWUSR)
    api_key = "X" * 40

    with mock.patch(
        "builtins.open",
        mock.mock_open(),
    ) as mock_file:
        mock_file.side_effect = [mock_file.return_value, OSError()]
        with pytest.raises(wandb_lib.apikey.WriteNetrcError) as expected_error:
            wandb_lib.apikey.write_netrc("http://localhost", "random-user", api_key)
        assert str(expected_error.value) == f"Unable to write {netrc_path}"


def test_read_apikey(tmp_path, monkeypatch):
    monkeypatch.setenv("NETRC", str(tmp_path / "netrc"))
    settings = wandb.Settings(base_url="http://localhost")
    netrc_path = str(tmp_path / "netrc")
    with open(netrc_path, "w") as f:
        f.write("machine localhost\n  login random-user\n  password " + "X" * 40)
    os.chmod(netrc_path, stat.S_IRUSR | stat.S_IWUSR)

    api_key = wandb_lib.apikey.api_key(settings)
    assert api_key == "X" * 40


def test_read_apikey_no_netrc_access(tmp_path, monkeypatch, mock_wandb_log):
    monkeypatch.setenv("NETRC", str(tmp_path / "netrc"))
    settings = wandb.Settings(base_url="http://localhost")
    netrc_path = str(tmp_path / "netrc")

    with mock.patch(
        "wandb.sdk.lib.apikey.check_netrc_access",
        return_value=wandb_lib.apikey._NetrcPermissions(
            exists=True,
            read_access=False,
            write_access=False,
        ),
    ):
        api_key = wandb_lib.apikey.api_key(settings)
        assert api_key is None
        assert mock_wandb_log.warned(f"Cannot access {netrc_path}.")


def test_apikey_prompt_str():
    app_url = "http://localhost"
    auth_base = f"{app_url}/authorize"
    prompt_str = f"You can find your API key in your browser here: {auth_base}"
    assert _api_key_prompt_str(app_url) == prompt_str
    assert _api_key_prompt_str(app_url, "weave") == f"{prompt_str}?ref=weave"
