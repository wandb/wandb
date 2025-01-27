import os
import stat

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
def test_write_netrc_permission_errors(tmp_path, mock_wandb_log, permission, error_msg):
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
        f"You do not have {error_msg} permissions for {netrc_path}"
    )
    assert mock_wandb_log.warned("We will be unable to save/update your API key.")
