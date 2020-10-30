from wandb import wandb_lib
import os


def test_write_netrc():
    api_key = "X" * 40
    wandb_lib.apikey.write_netrc("http://localhost", "vanpelt", api_key)
    with open(os.path.expanduser("~/.netrc")) as f:
        assert f.read() == (
            "machine localhost\n" "  login vanpelt\n" "  password %s\n" % api_key
        )
