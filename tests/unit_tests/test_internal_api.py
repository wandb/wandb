from __future__ import annotations

import base64
import hashlib
import os
import pathlib
import tempfile
from unittest.mock import Mock, patch

import pytest
import wandb.errors
import wandb.sdk.internal.internal_api
from pytest_mock import MockerFixture
from wandb.errors import CommError
from wandb.proto import wandb_api_pb2 as apb
from wandb.proto.wandb_internal_pb2 import ServerFeature
from wandb.sdk import wandb_setup
from wandb.sdk.internal.internal_api import Api
from wandb.sdk.lib import wbauth
from wandb.sdk.lib.service.service_connection import WandbApiFailedError
from wandb.sdk.sweeps import SweepNotFoundError


def test_agent_heartbeat_with_no_agent_id_fails():
    a = Api()
    with pytest.raises(ValueError):
        a.agent_heartbeat(None, {}, {})


def test_agent_heartbeat_raises_sweep_not_found_on_404():
    """Test that agent_heartbeat raises SweepNotFoundError on 404."""
    a = Api()

    error_response = apb.ApiErrorResponse(message="not found", http_status=404)
    error = WandbApiFailedError(error_response.message, error_response)

    with patch.object(a, "execute", side_effect=error):
        with pytest.raises(SweepNotFoundError):
            a.agent_heartbeat("test-agent-id", {}, {})


def test_agent_heartbeat_returns_empty_on_non_404_error():
    """Test that non-404 HTTP errors return empty list instead of raising."""
    a = Api()

    error_response = apb.ApiErrorResponse(message="server error", http_status=500)
    error = WandbApiFailedError(error_response.message, error_response)

    with patch.object(a, "execute", side_effect=error):
        result = a.agent_heartbeat("test-agent-id", {}, {})
        assert result == []


def test_get_run_state_invalid_kwargs():
    with pytest.raises(CommError) as e:
        _api = Api()

        def _mock_execute(*args, **kwargs):
            return dict()

        _api.execute = _mock_execute
        _api.get_run_state("test_entity", None, "test_run")

    assert "Error fetching run state" in str(e.value)


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


@pytest.mark.parametrize(
    "existing_contents,expect_download",
    [
        (None, True),
        ("outdated contents", True),
        ("current contents", False),
    ],
)
def test_download_write_file_fetches_iff_file_checksum_mismatched(
    existing_contents: str | None,
    expect_download: bool,
):
    url = "https://example.com/path/to/file.txt"
    current_contents = "current contents"
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = os.path.join(tmpdir, "file.txt")

        if existing_contents is not None:
            with open(filepath, "w") as f:
                f.write(existing_contents)

        api = Api()

        # Stand in for wandb-core, writing the file a real download would.
        def fake_download(request):
            path = request.download_file_request.path
            with open(path, "w") as f:
                f.write(current_contents)

        api._service_api.send_api_request = Mock(side_effect=fake_download)

        path, downloaded = api.download_write_file(
            metadata={
                "name": filepath,
                "md5": base64.b64encode(
                    hashlib.md5(current_contents.encode()).digest()
                ).decode(),
                "url": url,
            },
            out_dir=tmpdir,
        )

        assert downloaded == expect_download
        # Either way, the file on disk holds the current contents afterward.
        with open(path) as f:
            assert f.read() == current_contents


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


ENABLED_FEATURE_RESPONSE = {
    "serverInfo": {
        "features": [
            {"name": "LARGE_FILENAMES", "isEnabled": True},
            {"name": "ARTIFACT_TAGS", "isEnabled": False},
        ]
    }
}


@pytest.fixture
def mock_service_api(mocker: MockerFixture):
    mock = mocker.Mock()
    mock.settings.base_url = "https://api.wandb.ai"
    mock.settings.api_key = "test-api-key"
    mock.settings.identity_token_file = None
    mocker.patch(
        "wandb.sdk.internal.internal_api.Api._new_service_api",
        return_value=mock,
    )
    yield mock


@pytest.fixture
def mock_service_api_with_enabled_features(mock_service_api):
    mock_service_api.execute_graphql.return_value = ENABLED_FEATURE_RESPONSE
    yield mock_service_api


NO_FEATURES_RESPONSE = {"serverInfo": {"features": []}}


@pytest.fixture
def mock_service_api_with_no_features(mock_service_api):
    mock_service_api.execute_graphql.return_value = NO_FEATURES_RESPONSE
    yield mock_service_api


@pytest.fixture
def mock_service_api_with_error_no_field(mock_service_api):
    error_msg = 'Cannot query field "features" on type "ServerInfo".'
    mock_service_api.execute_graphql.side_effect = Exception(error_msg)
    yield mock_service_api


@pytest.fixture
def mock_service_api_with_random_error(mock_service_api):
    error_msg = "Some random error"
    mock_service_api.execute_graphql.side_effect = Exception(error_msg)
    yield mock_service_api


@pytest.mark.parametrize(
    "fixture_name, feature, expected_result, expected_error",
    [
        (
            # Test enabled features
            mock_service_api_with_enabled_features.__name__,
            ServerFeature.LARGE_FILENAMES,
            True,
            False,
        ),
        (
            # Test disabled features
            mock_service_api_with_enabled_features.__name__,
            ServerFeature.ARTIFACT_TAGS,
            False,
            False,
        ),
        (
            # Test features not in response
            mock_service_api_with_enabled_features.__name__,
            ServerFeature.ARTIFACT_REGISTRY_SEARCH,
            False,
            False,
        ),
        (
            # Test empty features list
            mock_service_api_with_no_features.__name__,
            ServerFeature.LARGE_FILENAMES,
            False,
            False,
        ),
        (
            # Test server not supporting features
            mock_service_api_with_error_no_field.__name__,
            ServerFeature.LARGE_FILENAMES,
            False,
            False,
        ),
        (
            # Test other server errors
            mock_service_api_with_random_error.__name__,
            ServerFeature.LARGE_FILENAMES,
            False,
            True,
        ),
    ],
)
@pytest.mark.usefixtures("patch_apikey", "patch_prompt")
def test_server_feature_checks(
    request,
    fixture_name,
    feature: ServerFeature,
    expected_result,
    expected_error,
):
    """Test check_server_feature with various scenarios."""
    request.getfixturevalue(fixture_name)
    api = Api()

    if expected_error:
        with pytest.raises(Exception, match="Some random error"):
            api._server_supports(feature)
    else:
        result = api._server_supports(feature)
        assert result == expected_result


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
