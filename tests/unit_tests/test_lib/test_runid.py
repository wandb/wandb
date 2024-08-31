from wandb.sdk.lib import runid


def test_generate_id_is_base36():
    # Given reasonable randomness assumptions, generating an 1000-digit string should
    # hit all 36 characters at least once >99.9999999999% of the time.
    new_id = runid.generate_id(1000)
    assert len(new_id) == 1000
    assert set(new_id) == set("0123456789abcdefghijklmnopqrstuvwxyz")


def test_generate_id_default_8_chars():
    assert len(runid.generate_id()) == 8
