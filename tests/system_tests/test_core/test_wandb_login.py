from unittest import mock

import pytest
import wandb


@pytest.mark.parametrize("verify", [None, True])
def test_login_valid_key(user, verify):
    with mock.patch.dict("os.environ", {"WANDB_API_KEY": ""}), mock.patch(
        "wandb.apis.internal.Api.validate_api_key",
        return_value=True,
    ):
        logged_in = wandb.login(key="A" * 40, verify=verify)
        assert logged_in
        assert wandb.api.api_key == "A" * 40


def test_login_invalid_key(user):
    with mock.patch.dict("os.environ", {"WANDB_API_KEY": ""}):
        with pytest.raises(wandb.errors.AuthenticationError):
            wandb.login(verify=True, key="I" * 40)
        assert wandb.api.api_key is None


def test_login_invalid_key_length(user):
    with mock.patch.dict("os.environ", {"WANDB_API_KEY": ""}):
        with pytest.raises(wandb.errors.AuthenticationError):
            wandb.login(verify=True, key="I")
        assert wandb.api.api_key is None


def test_login_invalid_key_no_verify(user):
    with mock.patch.dict("os.environ", {"WANDB_API_KEY": "I" * 40}):
        logged_in = wandb.login(verify=False)
        assert logged_in
        assert wandb.api.api_key == "I" * 40
