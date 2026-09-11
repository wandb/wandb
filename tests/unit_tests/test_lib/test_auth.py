import pathlib
import textwrap
from unittest.mock import MagicMock

import pytest
from wandb import env
from wandb.errors import AuthenticationError, UsageError
from wandb.sdk import wandb_setup
from wandb.sdk.lib import wbauth
from wandb.sdk.lib.wbauth import (
    AuthApiKey,
    AuthIdentityTokenFile,
    HostUrl,
    authenticate_session,
    identity_token_file,
    session_credentials,
    use_explicit_auth,
    validation,
)
from wandb.sdk.lib.wbauth.authenticate import _try_settings_file_auth

from tests.fixtures.mock_wandb_log import MockWandbLog

pytestmark = pytest.mark.usefixtures("skip_verify_login")


def _write_sso_account(path: pathlib.Path, host: str) -> None:
    """Saves credentials for a host, as `wandb login sso` does."""
    accounts = identity_token_file.Accounts()
    accounts.add(
        identity_token_file.Account(
            id_token="id-token",
            refresh_token="refresh-token",
            token_endpoint="https://idp.example.com/token",
            client_id="wandb-cli",
            host=host,
        )
    )
    accounts.save(path)


def _write_system_settings(contents: str) -> None:
    settings = wandb_setup.singleton().settings
    path = pathlib.Path(settings.settings_system)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(contents))
    settings.update_from_system_settings()


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


def test_identity_token_environment_variable_takes_priority_over_api_key(
    mock_wandb_log: MockWandbLog,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("WANDB_API_KEY", "from_env" * 5)
    monkeypatch.setenv("WANDB_IDENTITY_TOKEN_FILE", "file.jwt")

    result = authenticate_session(host="https://fake-url", source="test")

    assert isinstance(result, AuthIdentityTokenFile)
    assert result.path == pathlib.Path("file.jwt").absolute()
    mock_wandb_log.assert_warned(
        "Ignoring WANDB_API_KEY because federated identity credentials are"
        + " configured from WANDB_IDENTITY_TOKEN_FILE."
    )


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


def test_loads_identity_token_from_settings_file(
    mock_wandb_log: MockWandbLog,
    local_settings,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("WANDB_API_KEY", raising=False)
    monkeypatch.delenv("WANDB_IDENTITY_TOKEN_FILE", raising=False)

    token_path = tmp_path / "identity_token.json"
    _write_sso_account(token_path, "https://fake-url")
    _write_system_settings(
        f"""\
            [default]
            base_url = https://fake-url
            identity_token_file = {token_path}
        """
    )

    result = authenticate_session(host="https://fake-url", source="test")

    assert isinstance(result, AuthIdentityTokenFile)
    assert result.host.is_same_url("https://fake-url")
    assert result.path == token_path.absolute()
    mock_wandb_log.assert_logged(
        "[test] Loaded credentials for https://fake-url from"
        + " your saved SSO credentials."
    )


def test_identity_token_setting_takes_priority_over_api_key(
    mock_wandb_log: MockWandbLog,
    local_settings,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
):
    token_path = tmp_path / "identity_token.json"
    _write_sso_account(token_path, "https://fake-url")
    _write_system_settings(
        f"""\
            [default]
            base_url = https://fake-url
            identity_token_file = {token_path}
        """
    )
    monkeypatch.setenv("WANDB_API_KEY", "from_env" * 5)

    result = authenticate_session(host="https://fake-url", source="test")

    assert isinstance(result, AuthIdentityTokenFile)
    mock_wandb_log.assert_warned(
        "Ignoring WANDB_API_KEY because federated identity credentials are"
        + " configured from your saved SSO credentials."
    )


def test_loads_identity_token_from_default_path(
    mock_wandb_log: MockWandbLog,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv(env.API_KEY, raising=False)
    monkeypatch.delenv(env.IDENTITY_TOKEN_FILE, raising=False)
    monkeypatch.setenv(env.CONFIG_DIR, str(tmp_path))
    token_path = identity_token_file.default_path()
    token_path.parent.mkdir(exist_ok=True)
    _write_sso_account(token_path, "https://fake-url")

    result = authenticate_session(host="https://fake-url", source="test")

    assert isinstance(result, AuthIdentityTokenFile)
    assert result.path == token_path.absolute()
    mock_wandb_log.assert_logged(
        "[test] Loaded credentials for https://fake-url from"
        + " your saved SSO credentials."
    )


def test_default_identity_token_file_takes_priority_over_api_key(
    mock_wandb_log: MockWandbLog,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv(env.API_KEY, "from_env" * 5)
    monkeypatch.delenv(env.IDENTITY_TOKEN_FILE, raising=False)
    monkeypatch.setenv(env.CONFIG_DIR, str(tmp_path))
    token_path = identity_token_file.default_path()
    token_path.parent.mkdir(exist_ok=True)
    _write_sso_account(token_path, "https://fake-url")

    result = authenticate_session(host="https://fake-url", source="test")

    assert isinstance(result, AuthIdentityTokenFile)
    mock_wandb_log.assert_warned(
        "Ignoring WANDB_API_KEY because federated identity credentials are"
        + " configured from your saved SSO credentials."
    )


def test_falls_back_when_the_default_token_file_is_ambiguous(
    mock_wandb_log: MockWandbLog,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv(env.API_KEY, "from_env" * 5)
    monkeypatch.delenv(env.IDENTITY_TOKEN_FILE, raising=False)
    monkeypatch.setenv(env.CONFIG_DIR, str(tmp_path))
    token_path = identity_token_file.default_path()
    token_path.parent.mkdir(exist_ok=True)
    accounts = identity_token_file.Accounts()
    for org in ("acme", "globex"):
        accounts.add(
            identity_token_file.Account(
                id_token="id-token",
                refresh_token="refresh-token",
                token_endpoint="https://idp.example.com/token",
                client_id="wandb-cli",
                host="https://fake-url",
                org=org,
            )
        )
    accounts.active = None
    accounts.save(token_path)

    result = authenticate_session(host="https://fake-url", source="test")

    assert isinstance(result, AuthApiKey)
    mock_wandb_log.assert_warned("Several accounts are saved for https://fake-url")


def test_ignores_default_identity_token_file_for_different_host(
    mock_wandb_log: MockWandbLog,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv(env.API_KEY, "from_env" * 5)
    monkeypatch.delenv(env.IDENTITY_TOKEN_FILE, raising=False)
    monkeypatch.setenv(env.CONFIG_DIR, str(tmp_path))
    token_path = identity_token_file.default_path()
    token_path.parent.mkdir(exist_ok=True)
    _write_sso_account(token_path, "https://other-fake-url")

    result = authenticate_session(host="https://fake-url", source="test")

    assert isinstance(result, AuthApiKey)
    mock_wandb_log.assert_logged(
        "[test] Loaded credentials for https://fake-url from WANDB_API_KEY."
    )


def test_ignores_identity_token_setting_for_different_host(
    local_settings,
    tmp_path: pathlib.Path,
):
    _write_system_settings(
        f"""\
            [default]
            base_url = https://first.example.com
            identity_token_file = {tmp_path / "identity_token.json"}
        """
    )

    assert _try_settings_file_auth(host=HostUrl("https://second.example.com")) is None


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
