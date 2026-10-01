import datetime
import pathlib
import textwrap
from unittest.mock import MagicMock

import pytest
from wandb.errors import AuthenticationError, UsageError
from wandb.sdk import wandb_setup
from wandb.sdk.lib import wbauth
from wandb.sdk.lib.wbauth import (
    AuthApiKey,
    AuthBrowserLogin,
    AuthIdentityTokenFile,
    authenticate_session,
    browser_login,
    session_credentials,
    use_explicit_auth,
    validation,
)
from wandb.sdk.lib.wbauth.settings import set_auth_settings

from tests.fixtures.mock_wandb_log import MockWandbLog

pytestmark = pytest.mark.usefixtures("skip_verify_login")


def test_auth_repr_no_secrets():
    auth = AuthApiKey(host="https://test", api_key="test" * 10)

    assert repr(auth) == "<AuthApiKey host='https://test'>"


def test_auth_validates_key():
    with pytest.raises(
        AuthenticationError,
        match=r"API key must have 40\+ characters",
    ):
        AuthApiKey(host="https://test", api_key="too_short")


def test_use_explicit_auth(mock_wandb_log: MockWandbLog):
    auth = AuthApiKey(host="https://test", api_key="test" * 10)

    use_explicit_auth(auth, source="test")

    assert session_credentials(host="https://test") is auth
    mock_wandb_log.assert_logged(
        "[test] Using explicit session credentials for https://test."
    )


def test_warns_if_changing_auth(mock_wandb_log: MockWandbLog):
    auth1 = AuthApiKey(host="https://test1", api_key="auth_one" * 5)
    auth2 = AuthApiKey(host="https://test2", api_key="auth_two" * 5)

    use_explicit_auth(auth1, source="test")
    use_explicit_auth(auth2, source="test")

    assert session_credentials(host="https://test2") is auth2
    mock_wandb_log.assert_warned(
        "[test] Changing session credentials to explicit value for https://test2."
    )


def test_error_if_multiple_credentials_in_env(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("WANDB_API_KEY", "from_env" * 5)
    monkeypatch.setenv("WANDB_IDENTITY_TOKEN_FILE", "file.jwt")

    with pytest.raises(
        AuthenticationError,
        match="Both WANDB_API_KEY and WANDB_IDENTITY_TOKEN_FILE are set",
    ):
        authenticate_session(host="https://fake-url", source="test")


def test_loads_api_key_from_environment_variable(
    mock_wandb_log: MockWandbLog,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("WANDB_API_KEY", "from_env" * 5)

    result = authenticate_session(host="https://fake-url", source="test")

    assert isinstance(result, AuthApiKey)
    assert result.host.is_same_url("https://fake-url")
    assert result.api_key == "from_env" * 5
    mock_wandb_log.assert_logged(
        "[test] Loaded credentials for https://fake-url from WANDB_API_KEY."
    )


def test_verifies_system_credentials(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("WANDB_API_KEY", "test" * 40)
    check_validity = MagicMock(return_value=None)
    monkeypatch.setattr(validation, "check_api_key_validity", check_validity)

    result = authenticate_session(
        host="https://fake-url",
        source="test",
        verify=True,
    )

    assert isinstance(result, AuthApiKey)
    check_validity.assert_called_once()
    assert check_validity.call_args.kwargs["api_key"] == "test" * 40
    assert check_validity.call_args.kwargs["host"].is_same_url("https://fake-url")


def test_does_not_verify_system_credentials(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("WANDB_API_KEY", "test" * 40)
    check_validity = MagicMock(return_value=None)
    monkeypatch.setattr(validation, "check_api_key_validity", check_validity)

    result = authenticate_session(
        host="https://fake-url",
        source="test",
        verify=False,
    )

    assert isinstance(result, AuthApiKey)
    check_validity.assert_not_called()


def test_invalid_system_credentials_fail_verification(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("WANDB_API_KEY", "test" * 40)
    monkeypatch.setattr(
        validation,
        "check_api_key_validity",
        MagicMock(return_value="Key is invalid."),
    )

    with pytest.raises(AuthenticationError, match="Key is invalid."):
        authenticate_session(host="https://fake-url", source="test", verify=True)


def test_invalid_env_api_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WANDB_API_KEY", "invalid")

    with pytest.raises(
        AuthenticationError,
        match=r"WANDB_API_KEY invalid: API key must have 40\+ characters",
    ):
        authenticate_session(host="https://fake-url", source="test")


def test_loads_oidc_from_environment_variable(
    mock_wandb_log: MockWandbLog,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("WANDB_IDENTITY_TOKEN_FILE", "file.jwt")

    result = authenticate_session(host="https://fake-url", source="test")

    assert isinstance(result, AuthIdentityTokenFile)
    assert result.host.is_same_url("https://fake-url")
    # The path is absolutized so that the wandb-core service process,
    # whose working directory may differ, reads the intended file.
    assert result.path == pathlib.Path("file.jwt").absolute()
    assert result.path.is_absolute()
    mock_wandb_log.assert_logged(
        "[test] Loaded credentials for https://fake-url from"
        + " WANDB_IDENTITY_TOKEN_FILE."
    )


def test_reads_netrc(
    mock_wandb_log: MockWandbLog,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
):
    netrc = tmp_path / "test_netrc"
    password = "netrc" * 8
    netrc.write_text(
        textwrap.dedent(f"""\
            machine example.com
                login user
                password {password}
        """)
    )
    monkeypatch.setenv("NETRC", str(netrc))

    result = authenticate_session(host="https://example.com", source="test")

    assert isinstance(result, AuthApiKey)
    assert result.host.is_same_url("https://example.com")
    assert result.api_key == password
    mock_wandb_log.assert_logged(
        f"[test] Loaded credentials for https://example.com from {netrc}"
    )


@pytest.fixture
def stored_browser_login(monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    """Store a browser login for https://example.com, with nothing above it."""
    monkeypatch.delenv("WANDB_API_KEY", raising=False)
    monkeypatch.delenv("WANDB_IDENTITY_TOKEN_FILE", raising=False)

    credentials_file = pathlib.Path(wandb_setup.singleton().settings.credentials_file)
    browser_login.save_credentials(
        credentials_file,
        wbauth.HostUrl("https://example.com"),
        browser_login.TokenSet(
            access_token="wb_at_stored",
            refresh_token="wb_rt_stored",
            expires_at=datetime.datetime(2030, 1, 1, tzinfo=datetime.timezone.utc),
        ),
    )
    return credentials_file


def test_loads_a_stored_browser_login(
    mock_wandb_log: MockWandbLog,
    stored_browser_login: pathlib.Path,
):
    result = authenticate_session(host="https://example.com", source="test")

    assert isinstance(result, AuthBrowserLogin)
    assert result.host.is_same_url("https://example.com")
    assert result.credentials_path == stored_browser_login.absolute()
    mock_wandb_log.assert_logged(
        "[test] Loaded credentials for https://example.com"
        + f" from {stored_browser_login}."
    )


def test_browser_login_is_scoped_to_host(stored_browser_login: pathlib.Path):
    with pytest.raises(UsageError, match="No API key configured"):
        authenticate_session(host="https://other.invalid", source="test")


@pytest.mark.parametrize(
    "env_var, value, expected_type",
    [
        ("WANDB_API_KEY", "from_env" * 5, AuthApiKey),
        ("WANDB_IDENTITY_TOKEN_FILE", "file.jwt", AuthIdentityTokenFile),
    ],
)
def test_environment_outranks_a_browser_login(
    monkeypatch: pytest.MonkeyPatch,
    stored_browser_login: pathlib.Path,
    env_var: str,
    value: str,
    expected_type: type,
):
    monkeypatch.setenv(env_var, value)

    result = authenticate_session(host="https://example.com", source="test")

    assert isinstance(result, expected_type)


@pytest.mark.parametrize("source", ["netrc", "settings"])
def test_browser_login_outranks_stored_api_keys(
    stored_browser_login: pathlib.Path,
    source: str,
):
    if source == "netrc":
        wbauth.write_netrc_auth(host="https://example.com", api_key="netrc" * 8)
    else:
        settings = wandb_setup.singleton().settings
        settings.base_url = "https://example.com"
        settings.api_key = "settings" * 5

    result = authenticate_session(host="https://example.com", source="test")

    assert isinstance(result, AuthBrowserLogin)


def test_browser_login_verifies_against_the_server(
    monkeypatch: pytest.MonkeyPatch,
    stored_browser_login: pathlib.Path,
):
    check_validity = MagicMock(return_value=None)
    monkeypatch.setattr(validation, "check_browser_login_validity", check_validity)

    authenticate_session(host="https://example.com", source="test", verify=True)

    check_validity.assert_called_once()
    assert check_validity.call_args.kwargs["credentials_file"] == (
        stored_browser_login.absolute()
    )


def test_browser_login_settings_leave_no_other_credentials(
    stored_browser_login: pathlib.Path,
):
    settings = wandb_setup.singleton().settings.model_copy()
    settings.api_key = "settings" * 5
    settings.identity_token_file = "file.jwt"

    set_auth_settings(
        settings,
        AuthBrowserLogin(
            host="https://example.com",
            credentials_file=stored_browser_login,
        ),
    )

    assert settings.api_key is None
    assert settings.identity_token_file is None
    assert settings.credentials_file == str(stored_browser_login.absolute())
    assert settings.base_url == "https://example.com"


@pytest.mark.parametrize("source", ["settings", "environment", "netrc", "identity"])
def test_settings_credentials_are_a_fallback(monkeypatch, source):
    settings = wandb_setup.singleton().settings
    settings.api_key = "settings" * 5
    expected = settings.api_key
    if source == "environment":
        expected = "from_env" * 5
        monkeypatch.setenv("WANDB_API_KEY", expected)
    elif source == "netrc":
        expected = "netrc" * 8
        wbauth.write_netrc_auth(host=settings.base_url, api_key=expected)
    elif source == "identity":
        monkeypatch.setenv("WANDB_IDENTITY_TOKEN_FILE", "identity.jwt")

    auth = authenticate_session(host=settings.base_url, source="test")

    if source == "identity":
        assert isinstance(auth, AuthIdentityTokenFile)
    else:
        assert isinstance(auth, AuthApiKey)
        assert auth.api_key == expected


def test_settings_credentials_are_scoped_to_host():
    settings = wandb_setup.singleton().settings
    settings.api_key = "settings" * 5

    with pytest.raises(UsageError, match="No API key configured"):
        authenticate_session(host="https://other.invalid", source="test")


def test_jwt_bypasses_validation():
    """Internal client JWTs (3 dot-separated segments) bypass legacy API key validation."""
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiI0MiJ9.HMAC_SIGNATURE_HERE"
    auth = AuthApiKey(host="https://test", api_key=jwt)
    assert auth.api_key == jwt


@pytest.mark.parametrize(
    "key",
    [
        "header.payload",  # 2 segments
        "header.payload.signature.extra",  # 4 segments
        "bad header!.payload.signature",  # non-base64url character
    ],
)
def test_invalid_jwt_like_key_fails(key: str):
    """Dot-separated strings that don't match valid JWT structure are rejected."""
    with pytest.raises(AuthenticationError):
        AuthApiKey(host="https://test", api_key=key)
