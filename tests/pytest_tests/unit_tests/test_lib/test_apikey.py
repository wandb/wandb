import os

from wandb import wandb_lib


def test_write_netrc():
    api_key = "X" * 40
    res = wandb_lib.apikey.write_netrc("http://localhost", "vanpelt", api_key)
    assert res
    with open(os.path.expanduser("~/.netrc")) as f:
        assert f.read() == (
            "machine localhost\n" "  login vanpelt\n" "  password %s\n" % api_key
        )


def test_write_netrc_invalid_host():
    api_key = "X" * 40
    res = wandb_lib.apikey.write_netrc("http://foo", "vanpelt", api_key)
    assert res is None
