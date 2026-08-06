import os
from unittest import mock

import pytest
import wandb
from wandb.sdk.lib.wbauth import validation, wbnetrc


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


def test_login_explicit_valid_key_updates_netrc_and_validates_once(
    user: str,
    monkeypatch: pytest.MonkeyPatch,
):
    base_url = os.environ["WANDB_BASE_URL"]
    validations = mock.MagicMock(return_value=None)
    monkeypatch.setattr(validation, "check_api_key_validity", validations)

    assert wandb.login(key=user)

    assert wbnetrc.read_netrc_auth(host=base_url) == user
    assert validations.call_count == 1


def test_login_explicit_invalid_key_does_not_update_netrc(
    user: str,
    monkeypatch: pytest.MonkeyPatch,
):
    base_url = os.environ["WANDB_BASE_URL"]
    monkeypatch.delenv("WANDB_API_KEY", raising=False)
    validations = mock.MagicMock(wraps=validation.check_api_key_validity)
    monkeypatch.setattr(validation, "check_api_key_validity", validations)

    with pytest.raises(wandb.errors.AuthenticationError):
        wandb.login(key="X" * 40)

    assert wbnetrc.read_netrc_auth(host=base_url) is None
    assert validations.call_count == 1


def test_login_prompt_validates_each_input(
    user: str,
    emulated_terminal,
    monkeypatch: pytest.MonkeyPatch,
):
    """The prompt validates every key it is given, not just the first."""
    base_url = os.environ["WANDB_BASE_URL"]
    monkeypatch.delenv("WANDB_API_KEY", raising=False)
    validations = mock.MagicMock(wraps=validation.check_api_key_validity)
    monkeypatch.setattr(validation, "check_api_key_validity", validations)

    emulated_terminal.queue_input("2")  # "Use an existing W&B account"
    emulated_terminal.queue_input("I" * 40)  # rejected by the server
    emulated_terminal.queue_input("2")  # "Use an existing W&B account" again
    emulated_terminal.queue_input(user)  # then a valid key

    assert wandb.login(relogin=True)

    # Both the rejected and the accepted key are validated: one per input.
    assert validations.call_count == 2
    assert wbnetrc.read_netrc_auth(host=base_url) == user
