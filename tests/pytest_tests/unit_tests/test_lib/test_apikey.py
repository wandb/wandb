from wandb import wandb_lib


def test_write_netrc():
    api_key = "X" * 40
    res = wandb_lib.apikey.write_netrc("http://localhost", "vanpelt", api_key)
    assert res
    with open(wandb_lib.apikey.get_netrc_file_path()) as f:
        assert f.read() == (
            "machine localhost\n" "  login vanpelt\n" "  password %s\n" % api_key
        )
