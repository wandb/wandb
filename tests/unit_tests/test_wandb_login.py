import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import pytest
import wandb
from wandb.sdk import wandb_login, wandb_setup
from wandb.sdk.lib.credentials import _expires_at_fmt


def test_login_timeout(emulated_terminal):
    emulated_terminal.queue_input("junk")
    emulated_terminal.queue_input("more")

    logged_in = wandb.login(timeout=4)

    assert logged_in is False
    assert wandb.api.api_key is None
    assert wandb.setup().settings.mode == "disabled"


def test_login_timeout_choose(emulated_terminal):
    emulated_terminal.queue_input("3")

    logged_in = wandb.login(timeout=8)

    assert logged_in is False
    assert wandb.api.api_key is None
    assert wandb.setup().settings.mode == "offline"


def test_login_timeout_env_blank(emulated_terminal, monkeypatch):
    _ = emulated_terminal
    monkeypatch.setenv("WANDB_LOGIN_TIMEOUT", "4")

    logged_in = wandb.login()

    assert logged_in is False
    assert wandb.api.api_key is None
    assert wandb.setup().settings.mode == "disabled"


def test_login_timeout_env_invalid(emulated_terminal, monkeypatch):
    _ = emulated_terminal
    monkeypatch.setenv("WANDB_LOGIN_TIMEOUT", "junk")

    with pytest.raises(ValueError):
        wandb.login()


def test_relogin_timeout(emulated_terminal, dummy_api_key):
    assert wandb.login(relogin=True, key=dummy_api_key)
    terminal_state1 = emulated_terminal.read_stderr()

    assert wandb.login()
    terminal_state2 = emulated_terminal.read_stderr()

    # The second login should succeed immediately without printing.
    assert terminal_state1 == terminal_state2


def test_login_key(emulated_terminal):
    wandb.login(key="A" * 40)

    assert "Appending key" in "\n".join(emulated_terminal.read_stderr())
    assert wandb.api.api_key == "A" * 40


def test_login(test_settings):
    settings = test_settings(dict(mode="disabled"))
    wandb.setup(settings=settings)
    wandb.login()
    wandb.finish()


def test_login_anonymous(monkeypatch):
    monkeypatch.setenv("WANDB_API_KEY", "ANONYMOOSE" * 4)

    wandb.login(anonymous="must")

    assert wandb.api.api_key == "ANONYMOOSE" * 4
    assert wandb.setup().settings.anonymous == "must"


def test_login_sets_api_base_url(
    emulated_terminal,
    monkeypatch,
    local_settings,
    skip_verify_login,
):
    _ = emulated_terminal

    # HACK: Prevent the test from attempting to connect to the fake URLs.
    monkeypatch.setattr(
        wandb_login._WandbLogin,
        "_print_logged_in_message",
        lambda self: None,
    )

    monkeypatch.setenv("WANDB_API_KEY", "ANONYMOOSE" * 4)
    base_url = "https://api.test.host.ai"
    wandb.login(anonymous="must", host=base_url)

    assert wandb_setup.singleton().settings.base_url == base_url

    base_url = "https://api.wandb.ai"
    wandb.login(anonymous="must", host=base_url)

    assert wandb_setup.singleton().settings.base_url == base_url


def test_login_invalid_key():
    with mock.patch(
        "wandb.apis.internal.Api.validate_api_key",
        return_value=False,
    ):
        wandb.ensure_configured()
        with pytest.raises(wandb.errors.AuthenticationError):
            wandb.login(key="X" * 40, verify=True)

        assert wandb.api.api_key is None


# TODO: Make this a system test that runs agains the local-testcontainer?
@pytest.mark.skip(reason="Test has network calls")
def test_login_with_token_file(tmp_path: Path):
    token_file = str(tmp_path / "jwt.txt")
    credentials_file = str(tmp_path / "credentials.json")
    base_url = "https://api.wandb.ai"

    with open(token_file, "w") as f:
        f.write("eyaksdcmlasfm")

    expires_at = datetime.now() + timedelta(days=5)
    data = {
        "credentials": {
            base_url: {
                "access_token": "wb_at_ksdfmlaskfm",
                "expires_at": expires_at.strftime(_expires_at_fmt),
            }
        }
    }
    with open(credentials_file, "w") as f:
        json.dump(data, f)

    with mock.patch.dict(
        "os.environ",
        WANDB_IDENTITY_TOKEN_FILE=token_file,
        WANDB_CREDENTIALS_FILE=credentials_file,
    ):
        wandb.login()
        assert wandb.api.is_authenticated
