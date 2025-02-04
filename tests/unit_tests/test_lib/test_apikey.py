import os
import stat
from unittest import mock

import pytest
from wandb import wandb, wandb_lib


def test_write_netrc():
    api_key = "X" * 40
    res = wandb_lib.apikey.write_netrc("http://localhost", "vanpelt", api_key)
    assert res
    with open(wandb_lib.apikey.get_netrc_file_path()) as f:
        assert f.read() == (
            "machine localhost\n  login vanpelt\n  password {}\n".format(api_key)
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
        return_value={
            wandb_lib.apikey._NetrcPermissions.NETRC_EXISTS: True,
            wandb_lib.apikey._NetrcPermissions.NETRC_READ_ACCESS: read_permission,
            wandb_lib.apikey._NetrcPermissions.NETRC_WRITE_ACCESS: write_permission,
        },
    ):
        logged_in = wandb_lib.apikey.write_netrc(
            "http://localhost", "random-user", api_key
        )
        assert not logged_in
        assert mock_wandb_log.warned(
            f"Cannot access {netrc_path}. In order to persist your API key,"
            + "\nGrant read & write permissions for your user to the file,"
            + '\nor specify a different file with the environment variable "NETRC={new_netrc_path}".'
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
        logged_in = wandb_lib.apikey.write_netrc(
            "http://localhost", "random-user", api_key
        )
        assert not logged_in
        assert mock_wandb_log.errored(f"Unable to read permissions for {netrc_path}")


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
        mock_file.side_effect = OSError
        logged_in = wandb_lib.apikey.write_netrc(
            "http://localhost", "random-user", api_key
        )
        assert not logged_in
        assert mock_wandb_log.errored(f"Unable to write {netrc_path}")


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
        return_value={
            wandb_lib.apikey._NetrcPermissions.NETRC_EXISTS: True,
            wandb_lib.apikey._NetrcPermissions.NETRC_READ_ACCESS: False,
            wandb_lib.apikey._NetrcPermissions.NETRC_WRITE_ACCESS: False,
        },
    ):
        api_key = wandb_lib.apikey.api_key(settings)
        assert api_key is None
        assert mock_wandb_log.warned(
            f"Cannot access {netrc_path}.\n" + "Prompting for API key."
        )
