from unittest.mock import MagicMock

import pytest
import wandb
from wandb.errors import UsageError
from wandb.sdk import wandb_login, wandb_setup
from wandb.sdk.lib.service.service_connection import WandbApiFailedError


@pytest.fixture(autouse=True)
def suppress_logged_in_message(monkeypatch: pytest.MonkeyPatch) -> None:
    # HACK: Prevent the test from attempting to connect to the fake URLs.
    #
    # The banner fetches viewer info; keep login unit tests focused on prompt
    # and config behavior instead of network-backed account lookups.
    monkeypatch.setattr(
        wandb_login,
        "_print_logged_in_message",
        lambda *args, **kwargs: None,
    )


def test_login_timeout(emulated_terminal):
    emulated_terminal.queue_input("junk")
    emulated_terminal.queue_input("more")

    logged_in = wandb.login(timeout=4)

    assert logged_in is False
    assert wandb.api.api_key is None
    assert wandb.setup().settings.mode == "disabled"


def test_login_no_terminput():
    """Raise if key not configured and interactive prompt unavailable."""
    with pytest.raises(UsageError, match="No API key configured"):
        wandb.login()


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


@pytest.mark.usefixtures("skip_verify_login")
def test_relogin_timeout(emulated_terminal, dummy_api_key):
    assert wandb.login(relogin=True, key=dummy_api_key)
    terminal_state1 = emulated_terminal.read_stderr()

    assert wandb.login()
    terminal_state2 = emulated_terminal.read_stderr()

    # The second login should succeed immediately without printing.
    assert terminal_state1 == terminal_state2


@pytest.mark.usefixtures("skip_verify_login")
def test_login_key(emulated_terminal):
    wandb.login(key="A" * 40)

    assert "Appending key" in "\n".join(emulated_terminal.read_stderr())
    assert wandb.api.api_key == "A" * 40


def test_login(test_settings):
    settings = test_settings(dict(mode="disabled"))
    wandb.setup(settings=settings)
    wandb.login()
    wandb.finish()


@pytest.mark.usefixtures(
    "emulated_terminal",
    "local_settings",
    "skip_verify_login",
)
def test_login_sets_api_base_url():
    base_url = "https://api.test.host.ai"
    wandb.login(key="test" * 10, host=base_url)
    assert wandb_setup.singleton().settings.base_url == base_url

    base_url = "https://api.wandb.ai"
    wandb.login(key="test" * 10, host=base_url)
    assert wandb_setup.singleton().settings.base_url == base_url


def test_login_verify_wraps_service_errors(monkeypatch: pytest.MonkeyPatch):
    """Any verification failure surfaces as the documented AuthenticationError.

    Failures to start or connect to the wandb-core service raise exception
    types other than WandbApiFailedError.
    """

    def raise_service_error(self, *args, **kwargs):
        raise ConnectionRefusedError("the service process is not running")

    monkeypatch.setattr(
        "wandb.sdk.wandb_login.ServiceApi.authenticate",
        raise_service_error,
    )
    wandb.ensure_configured()

    with pytest.raises(wandb.errors.AuthenticationError):
        wandb.login(key="X" * 40, verify=True)


def test_login_invalid_key(monkeypatch: pytest.MonkeyPatch):
    def reject_credentials(self, *args, **kwargs):
        raise WandbApiFailedError("invalid credentials")

    monkeypatch.setattr(
        "wandb.sdk.wandb_login.ServiceApi.authenticate",
        reject_credentials,
    )
    wandb.ensure_configured()

    with pytest.raises(wandb.errors.AuthenticationError):
        wandb.login(key="X" * 40, verify=True)


def test_login_explicit_invalid_key_does_not_update_netrc(
    monkeypatch: pytest.MonkeyPatch,
):
    """An explicit key rejected by the server must not be saved to .netrc."""
    monkeypatch.setattr(
        "wandb.apis.public.service_api.ServiceApi.authenticate",
        MagicMock(side_effect=WandbApiFailedError("invalid credentials")),
    )
    write_netrc = MagicMock()
    monkeypatch.setattr("wandb.sdk.lib.wbauth.write_netrc_auth", write_netrc)

    with pytest.raises(wandb.errors.AuthenticationError):
        wandb.login(key="X" * 40, verify=True)

    write_netrc.assert_not_called()


def test_login_explicit_valid_key_updates_netrc(
    monkeypatch: pytest.MonkeyPatch,
):
    """An explicit key accepted by the server is saved to .netrc."""
    monkeypatch.setattr(
        "wandb.apis.public.service_api.ServiceApi.authenticate",
        MagicMock(),
    )
    write_netrc = MagicMock()
    monkeypatch.setattr("wandb.sdk.lib.wbauth.write_netrc_auth", write_netrc)

    wandb.login(key="X" * 40, verify=True)

    write_netrc.assert_called_once()
    assert write_netrc.call_args.kwargs["api_key"] == "X" * 40


def test_login_verify_with_token_file(federated_identity):
    """Regression test for gh-11722: federated identity in wandb.login().

    Verification goes through wandb-core, which exchanges the identity
    token for an access token and authenticates with it as a Bearer token.
    """
    logged_in = wandb.login(verify=True)

    assert logged_in is True
    assert federated_identity.token_exchanges >= 1
    assert federated_identity.graphql_auth_headers
    assert all(
        header == f"Bearer {federated_identity.access_token}"
        for header in federated_identity.graphql_auth_headers
    )


def test_login_verify_with_token_file_rejected(federated_identity):
    federated_identity.valid = False

    with pytest.raises(wandb.errors.AuthenticationError):
        wandb.login(verify=True)
