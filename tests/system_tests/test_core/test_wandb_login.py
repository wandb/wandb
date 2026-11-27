import os
from unittest import mock

import pytest
import wandb
from wandb.sdk.lib.wbauth import wbnetrc


def test_login_valid_key(user):
    logged_in = wandb.login(verify=True)
    assert logged_in


def test_login_invalid_key_from_environment_raises(user):
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


def test_login_explicit_valid_key_updates_netrc(
    user: str,
    monkeypatch: pytest.MonkeyPatch,
):
    base_url = os.environ["WANDB_BASE_URL"]

    assert wandb.login(key=user)

    assert wbnetrc.read_netrc_auth(host=base_url) == user


def test_login_explicit_invalid_key_does_not_update_netrc(
    user: str,
    monkeypatch: pytest.MonkeyPatch,
):
    base_url = os.environ["WANDB_BASE_URL"]
    monkeypatch.delenv("WANDB_API_KEY", raising=False)

    with pytest.raises(wandb.errors.AuthenticationError):
        wandb.login(key="X" * 40)

    assert wbnetrc.read_netrc_auth(host=base_url) is None
