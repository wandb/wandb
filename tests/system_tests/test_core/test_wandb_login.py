from unittest import mock

import pytest
import wandb


@pytest.mark.parametrize("verify", [None, True])
def test_login_valid_key(user, verify):
    logged_in = wandb.login(verify=verify)
    assert logged_in


def test_login_invalid_key(user):
    with mock.patch.dict("os.environ", {"WANDB_API_KEY": "I" * 40}):
        with pytest.raises(wandb.errors.AuthenticationError):
            wandb.login(verify=True)


def test_login_invalid_key_no_verify(user):
    with mock.patch.dict("os.environ", {"WANDB_API_KEY": "I" * 40}):
        logged_in = wandb.login(verify=False)
        assert logged_in


def test_login_invalid_key_length(user):
    with mock.patch.dict("os.environ", {"WANDB_API_KEY": ""}):
        with pytest.raises(wandb.errors.AuthenticationError):
            wandb.login(verify=True, key="I")
