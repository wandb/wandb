from wandb.sdk.lib import hashutil


def test_md5_string():
    assert hashutil.md5_string("") == "1B2M2Y8AsgTpgAmY7PhCfg=="
    assert hashutil.md5_string("foo") == "rL0Y20zC+Fzt72VPzMSk2A=="
