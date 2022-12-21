from wandb.sdk.lib import runid


def test_generate_id_is_base36():
    # Given reasonable randomness assumptions, generating an 1000-digit string should
    # hit all 36 characters at least once >99.9999999999% of the time.
    id = runid.generate_id(1000)
    assert set(id) == set("0123456789abcdefghijklmnopqrstuvwxyz")
