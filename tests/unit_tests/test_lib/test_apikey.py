import os
import stat
from unittest import mock

import pytest
from wandb import wandb_lib


def test_write_netrc():
    api_key = "X" * 40
    res = wandb_lib.apikey.write_netrc("http://localhost", "vanpelt", api_key)
    assert res
    with open(wandb_lib.apikey.get_netrc_file_path()) as f:
        assert f.read() == (
            "machine localhost\n  login vanpelt\n  password {}\n".format(api_key)
        )


@pytest.mark.parametrize(
    "permission,error_msg",
    [
        (stat.S_IWUSR, "read"),
        (stat.S_IRUSR, "write"),
    ],
)
def test_netrc_permission_errors(tmp_path, mock_wandb_log, permission, error_msg):
    netrc_path = str(tmp_path / "netrc")
    os.environ["NETRC"] = netrc_path
    with open(netrc_path, "w") as f:
        f.write("")
    os.chmod(netrc_path, permission)
    api_key = "X" * 40
    logged_in = wandb_lib.apikey.write_netrc(
        "http://localhost", "jacob-romero", api_key
    )
    assert not logged_in
    assert mock_wandb_log.warned(
        f"Cannot access {netrc_path}. In order to persist your API key,"
        + "\nGrant read & write permissions for your user to the file,"
        + '\nor specify a different file with the environment variable "NETRC={new_netrc_path}".'
    )


def test_write_netrc_permission_oserror(tmp_path, mock_wandb_log):
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
            "http://localhost", "jacob-romero", api_key
        )
        assert not logged_in
        assert mock_wandb_log.errored(f"Unable to read permissions for {netrc_path}")
