from __future__ import annotations

import pathlib

import pytest
import wandb.errors
import wandb.sdk.internal.internal_api
from pytest_mock import MockerFixture
from wandb.proto import wandb_api_pb2 as apb
from wandb.sdk import wandb_setup
from wandb.sdk.internal.internal_api import Api
from wandb.sdk.lib import wbauth
from wandb.sdk.lib.service.service_connection import WandbApiFailedError
from wandb.sdk.sweeps import SweepNotFoundError


def test_execute_propagates_service_api_errors(mocker: MockerFixture):
    service_api = mocker.Mock()
    service_api.settings.base_url = "https://api.wandb.ai"
    service_api.settings.api_key = "test-api-key"
    service_api.settings.identity_token_file = None
    error_response = apb.ApiErrorResponse(message="server unavailable")
    service_api.execute_graphql.side_effect = WandbApiFailedError(
        error_response.message,
        error_response,
    )
    mocker.patch(
        "wandb.sdk.internal.internal_api.Api._new_service_api",
        return_value=service_api,
    )
    api = Api()

    with pytest.raises(WandbApiFailedError):
        api.execute("query Viewer { viewer { id } }")

    service_api.execute_graphql.assert_called_once_with(
        "query Viewer { viewer { id } }"
    )


def test_internal_api_with_no_write_global_config_dir(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
):
    config_dir = tmp_path / "test-config"
    monkeypatch.setenv("WANDB_CONFIG_DIR", str(config_dir))
    config_dir.mkdir(0o511)  # read and list only

    try:
        Api()
    finally:
        config_dir.chmod(0o711)  # allow test to clean up


class TestJWTAuth:
    def test_jwt_auth_builds_no_authorization_header(self, tmp_path: pathlib.Path):
        # wandb-core resolves federated identity credentials from the
        # settings itself; Python does not build an Authorization header.
        token_file = tmp_path / "token.jwt"
        token_file.write_text("test.jwt.token")

        environ = {"WANDB_IDENTITY_TOKEN_FILE": str(token_file)}
        api = Api(environ=environ)

        assert "Authorization" not in api._extra_http_headers
        assert api.request_auth is None

    def test_api_key_takes_precedence_over_jwt(
        self, tmp_path: pathlib.Path, mocker: MockerFixture
    ):
        token_file = tmp_path / "token.jwt"
        token_file.write_text("test.jwt.token")

        fetch_mock = mocker.patch(
            "wandb.apis.public.service_api.ServiceApi.access_token",
            return_value="test_access_token",
        )

        environ = {"WANDB_IDENTITY_TOKEN_FILE": str(token_file)}
        api = Api(
            default_settings={"api_key": "a" * 40},
            environ=environ,
        )

        fetch_mock.assert_not_called()
        assert api.request_auth == ("api", "a" * 40)

    def test_session_api_key_takes_precedence_over_jwt(
        self, tmp_path: pathlib.Path, mocker: MockerFixture
    ):
        token_file = tmp_path / "token.jwt"
        token_file.write_text("test.jwt.token")

        fetch_mock = mocker.patch(
            "wandb.apis.public.service_api.ServiceApi.access_token",
            return_value="test_access_token",
        )
        wbauth.use_explicit_auth(
            wbauth.AuthApiKey(host="https://api.wandb.ai", api_key="a" * 40),
            source="test",
        )
        # Simulate global settings that read the environment variable after
        # login, as in a forked process.
        wandb_setup.singleton().settings.identity_token_file = str(token_file)

        environ = {"WANDB_IDENTITY_TOKEN_FILE": str(token_file)}
        api = Api(environ=environ)

        fetch_mock.assert_not_called()
        assert api.request_auth == ("api", "a" * 40)
        assert api._service_api._settings.api_key == "a" * 40
        assert api._service_api._settings.identity_token_file is None

    def test_session_identity_token_file_uses_jwt(self, tmp_path: pathlib.Path):
        token_file = tmp_path / "token.jwt"
        token_file.write_text("test.jwt.token")
        wbauth.use_explicit_auth(
            wbauth.AuthIdentityTokenFile(
                host="https://api.wandb.ai",
                path=str(token_file),
                credentials_file=str(tmp_path / "credentials.json"),
            ),
            source="test",
        )

        api = Api(environ={})

        assert api.request_auth is None

    def test_access_token_none_without_identity_token(self, mocker: MockerFixture):
        # Without federated identity, the token is None and no request is
        # sent to wandb-core.
        api = Api(environ={})
        send_mock = mocker.patch(
            "wandb.apis.public.service_api.ServiceApi.send_api_request"
        )

        assert api._service_api.access_token() is None
        send_mock.assert_not_called()

    def test_access_token_raises_for_missing_file(self, tmp_path: pathlib.Path):
        missing_file = tmp_path / "nonexistent.jwt"
        environ = {"WANDB_IDENTITY_TOKEN_FILE": str(missing_file)}

        with pytest.raises(wandb.errors.AuthenticationError, match="not found"):
            Api(environ=environ)

    def test_access_token_via_wandb_core(self, federated_identity):
        """End-to-end: the token exchange happens in wandb-core."""
        api = Api()

        access_token = api._service_api.access_token()

        assert access_token == federated_identity.access_token
        assert federated_identity.token_exchanges >= 1
