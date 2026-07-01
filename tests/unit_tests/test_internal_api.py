from __future__ import annotations

import base64
import hashlib
import os
import pathlib
import tempfile
from collections.abc import Callable, Mapping
from itertools import chain
from pathlib import Path
from typing import TypeVar
from unittest.mock import Mock, patch

import pytest
import requests
import wandb.errors
import wandb.sdk.internal.internal_api
import wandb.sdk.internal.progress
from pytest_mock import MockerFixture
from responses import RequestsMock
from wandb.apis import internal
from wandb.errors import CommError
from wandb.proto import wandb_api_pb2 as apb
from wandb.proto.wandb_internal_pb2 import ServerFeature
from wandb.sdk.internal.internal_api import (
    _match_org_with_fetched_org_entities,
    _OrgNames,
)
from wandb.sdk.launch.sweeps import SweepNotFoundError
from wandb.sdk.lib import retry
from wandb.sdk.lib.service.service_connection import WandbApiFailedError

from .test_retry import MockTime, mock_time  # noqa: F401

_T = TypeVar("_T")


@pytest.fixture
def mock_responses():
    with RequestsMock() as rsps:
        yield rsps


def test_agent_heartbeat_with_no_agent_id_fails():
    a = internal.Api()
    with pytest.raises(ValueError):
        a.agent_heartbeat(None, {}, {})


def test_agent_heartbeat_raises_sweep_not_found_on_404():
    """Test that agent_heartbeat raises SweepNotFoundError on 404."""
    a = internal.Api()

    error_response = apb.ApiErrorResponse(message="not found", http_status=404)
    error = WandbApiFailedError(error_response.message, error_response)

    with patch.object(a.api, "execute", side_effect=error):
        with pytest.raises(SweepNotFoundError):
            a.agent_heartbeat("test-agent-id", {}, {})


def test_agent_heartbeat_returns_empty_on_non_404_error():
    """Test that non-404 HTTP errors return empty list instead of raising."""
    a = internal.Api()

    error_response = apb.ApiErrorResponse(message="server error", http_status=500)
    error = WandbApiFailedError(error_response.message, error_response)

    with patch.object(a.api, "execute", side_effect=error):
        result = a.agent_heartbeat("test-agent-id", {}, {})
        assert result == []


def test_get_run_state_invalid_kwargs():
    with pytest.raises(CommError) as e:
        _api = internal.Api()

        def _mock_execute(*args, **kwargs):
            return dict()

        _api.api.execute = _mock_execute
        _api.get_run_state("test_entity", None, "test_run")

    assert "Error fetching run state" in str(e.value)


def test_execute_propagates_service_api_errors(mocker: MockerFixture):
    service_api = mocker.Mock()
    error_response = apb.ApiErrorResponse(message="server unavailable")
    service_api.execute_graphql.side_effect = WandbApiFailedError(
        error_response.message,
        error_response,
    )
    mocker.patch(
        "wandb.sdk.internal.internal_api.Api._new_service_api",
        return_value=service_api,
    )
    api = internal.InternalApi()

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

        api = internal.InternalApi()

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
        internal.InternalApi()
    finally:
        config_dir.chmod(0o711)  # allow test to clean up


@pytest.fixture
def mock_gql():
    with patch("wandb.sdk.internal.internal_api.Api.execute") as mock:
        mock.return_value = None
        yield mock


def test_fetch_orgs_from_team_entity(mock_gql):
    """Test fetching organization entities from a team entity."""
    api = internal.InternalApi()
    mock_gql.return_value = {
        "entity": {
            "organization": {
                "name": "test-org",
                "orgEntity": {"name": "test-org-entity"},
            },
            "user": None,
        }
    }
    result = api._fetch_orgs_and_org_entities_from_entity("team-entity")
    assert result == [_OrgNames(entity_name="test-org-entity", display_name="test-org")]


def test_fetch_orgs_from_personal_entity_single_org(mock_gql):
    """Test fetching organization entities from a personal entity with single org."""
    api = internal.InternalApi()
    mock_gql.return_value = {
        "entity": {
            "organization": None,
            "user": {
                "organizations": [
                    {
                        "name": "personal-org",
                        "orgEntity": {"name": "personal-org-entity"},
                    }
                ]
            },
        }
    }
    result = api._fetch_orgs_and_org_entities_from_entity("personal-entity")
    assert result == [
        _OrgNames(entity_name="personal-org-entity", display_name="personal-org")
    ]


def test_fetch_orgs_from_personal_entity_multiple_orgs(mock_gql):
    """Test fetching organization entities from a personal entity with multiple orgs."""
    api = internal.InternalApi()
    mock_gql.return_value = {
        "entity": {
            "organization": None,
            "user": {
                "organizations": [
                    {
                        "name": "org1",
                        "orgEntity": {"name": "org1-entity"},
                    },
                    {
                        "name": "org2",
                        "orgEntity": {"name": "org2-entity"},
                    },
                ]
            },
        }
    }
    result = api._fetch_orgs_and_org_entities_from_entity("personal-entity")
    assert result == [
        _OrgNames(entity_name="org1-entity", display_name="org1"),
        _OrgNames(entity_name="org2-entity", display_name="org2"),
    ]


def test_fetch_orgs_from_personal_entity_no_orgs(mock_gql):
    """Test fetching organization entities from a personal entity with no orgs."""
    api = internal.InternalApi()
    mock_gql.return_value = {
        "entity": {
            "organization": None,
            "user": {"organizations": []},
        }
    }
    with pytest.raises(
        ValueError,
        match="Unable to resolve an organization associated with personal entity",
    ):
        api._fetch_orgs_and_org_entities_from_entity("personal-entity")


def test_fetch_orgs_from_nonexistent_entity(mock_gql):
    """Test fetching organization entities from a nonexistent entity."""
    api = internal.InternalApi()
    mock_gql.return_value = {
        "entity": {
            "organization": None,
            "user": None,
        }
    }
    with pytest.raises(
        ValueError,
        match="Unable to find an organization under entity",
    ):
        api._fetch_orgs_and_org_entities_from_entity("potato-entity")


def test_fetch_orgs_with_invalid_response_structure(mock_gql):
    """Test fetching organization entities with invalid response structure."""
    api = internal.InternalApi()
    mock_gql.return_value = {
        "entity": {
            "organization": {
                "name": "hello",
                "orgEntity": None,
            },
            "user": None,
        }
    }
    with pytest.raises(ValueError, match="Unable to find an organization under entity"):
        api._fetch_orgs_and_org_entities_from_entity("invalid-entity")


def test_match_org_single_org_display_name_match():
    assert (
        _match_org_with_fetched_org_entities(
            "org-display",
            [_OrgNames(entity_name="org-entity", display_name="org-display")],
        )
        == "org-entity"
    )


def test_match_org_single_org_entity_name_match():
    assert (
        _match_org_with_fetched_org_entities(
            "org-entity",
            [_OrgNames(entity_name="org-entity", display_name="org-display")],
        )
        == "org-entity"
    )


def test_match_org_multiple_orgs_successful_match():
    assert (
        _match_org_with_fetched_org_entities(
            "org-display-2",
            [
                _OrgNames(entity_name="org-entity", display_name="org-display"),
                _OrgNames(entity_name="org-entity-2", display_name="org-display-2"),
            ],
        )
        == "org-entity-2"
    )


def test_match_org_single_org_no_match():
    with pytest.raises(
        ValueError, match="Expecting the organization name or entity name to match"
    ):
        _match_org_with_fetched_org_entities(
            "wrong-org",
            [_OrgNames(entity_name="org-entity", display_name="org-display")],
        )


def test_match_org_multiple_orgs_no_match():
    with pytest.raises(
        ValueError, match="Personal entity belongs to multiple organizations"
    ):
        _match_org_with_fetched_org_entities(
            "wrong-org",
            [
                _OrgNames(entity_name="org1-entity", display_name="org1-display"),
                _OrgNames(entity_name="org2-entity", display_name="org2-display"),
            ],
        )


@pytest.fixture
def api_with_single_org():
    api = internal.InternalApi()
    api._fetch_orgs_and_org_entities_from_entity = Mock(
        return_value=[_OrgNames(entity_name="org-entity", display_name="org-display")]
    )
    return api


@pytest.mark.parametrize(
    "entity, input_org, expected_org_entity",
    [
        ("entity", "org-display", "org-entity"),
        ("entity", "org-entity", "org-entity"),
        ("entity", None, "org-entity"),
    ],
)
def test_resolve_org_entity_name_with_single_org_success(
    api_with_single_org, entity, input_org, expected_org_entity
):
    assert (
        api_with_single_org._resolve_org_entity_name(entity, input_org)
        == expected_org_entity
    )


@pytest.mark.parametrize(
    "entity,input_org,error_message",
    [
        (
            "entity",
            "potato-org",
            "Expecting the organization name or entity name to match",
        ),
        (None, None, "Entity name is required to resolve org entity name."),
        ("", None, "Entity name is required to resolve org entity name."),
    ],
)
def test_resolve_org_entity_name_with_single_org_errors(
    api_with_single_org, entity, input_org, error_message
):
    with pytest.raises(ValueError, match=error_message):
        api_with_single_org._resolve_org_entity_name(entity, input_org)


@pytest.fixture
def api_with_multiple_orgs():
    api = internal.InternalApi()
    api._fetch_orgs_and_org_entities_from_entity = Mock(
        return_value=[
            _OrgNames(entity_name="org1-entity", display_name="org1-display"),
            _OrgNames(entity_name="org2-entity", display_name="org2-display"),
            _OrgNames(entity_name="org3-entity", display_name="org3-display"),
        ]
    )
    return api


def test_resolve_org_entity_name_with_multiple_orgs_no_org_specified(
    api_with_multiple_orgs,
):
    """Test that error is raised when no org is specified for entity with multiple orgs."""
    with pytest.raises(ValueError, match="belongs to multiple organizations"):
        api_with_multiple_orgs._resolve_org_entity_name("entity")


def test_resolve_org_entity_name_with_multiple_orgs_display_name(
    api_with_multiple_orgs,
):
    """Test resolving org entity name using org display name."""
    assert (
        api_with_multiple_orgs._resolve_org_entity_name("entity", "org1-display")
        == "org1-entity"
    )


def test_resolve_org_entity_name_with_multiple_orgs_entity_name(api_with_multiple_orgs):
    """Test resolving org entity name using org entity name."""
    assert (
        api_with_multiple_orgs._resolve_org_entity_name("entity", "org2-entity")
        == "org2-entity"
    )


def test_resolve_org_entity_name_with_multiple_orgs_invalid_org(api_with_multiple_orgs):
    """Test that error is raised when specified org doesn't match any available orgs."""
    with pytest.raises(
        ValueError, match="Personal entity belongs to multiple organizations"
    ):
        api_with_multiple_orgs._resolve_org_entity_name("entity", "potato-org")


MockResponseOrException = Exception | tuple[int, Mapping[int, int], str]


class TestUploadFile:
    """Tests `upload_file`."""

    def test_routes_non_azure_uploads_through_core(self, example_file: Path):
        """Non-Azure uploads are sent to wandb-core as an UploadFileRequest.

        Retries, timeouts, and the AWS-specific transient-error handling that
        used to live here are now owned by wandb-core's file transfer subsystem.
        """
        api = internal.InternalApi()
        api._service_api.send_api_request = Mock()

        with example_file.open("rb") as file:
            result = api.upload_file(
                "http://example.com/upload-dst",
                file,
                extra_headers={"X-Test": "test"},
            )

        assert result is None
        api._service_api.send_api_request.assert_called_once()
        request = api._service_api.send_api_request.call_args[0][0]
        upload = request.upload_file_request
        assert upload.url == "http://example.com/upload-dst"
        assert upload.path == str(example_file.resolve())
        assert upload.headers["X-Test"] == "test"

    def test_propagates_core_errors(self, example_file: Path):
        """Failures from wandb-core propagate to the caller."""
        api = internal.InternalApi()
        api._service_api.send_api_request = Mock(
            side_effect=WandbApiFailedError("upload failed")
        )

        with example_file.open("rb") as file:
            with pytest.raises(WandbApiFailedError):
                api.upload_file("http://example.com/upload-dst", file)

    class TestAzure:
        MAGIC_HEADERS = {"x-ms-blob-type": "SomeBlobType"}

        def test_uses_azure_lib_if_available(self, example_file: Path):
            api = internal.InternalApi()
            api._azure_blob_module = Mock()

            api.upload_file(
                "http://example.com/upload-dst",
                example_file.open("rb"),
                extra_headers=self.MAGIC_HEADERS,
            )

            api._azure_blob_module.BlobClient.from_blob_url().upload_blob.assert_called_once()

        @pytest.mark.parametrize(
            "response,expected_errtype,check_err",
            [
                (
                    (400, {}, "my-reason"),
                    requests.RequestException,
                    lambda e: e.response.status_code == 400 and "my-reason" in str(e),
                ),
                (
                    (500, {}, "my-reason"),
                    retry.TransientError,
                    lambda e: (
                        e.exception.response.status_code == 500
                        and "my-reason" in str(e.exception)
                    ),
                ),
                (
                    requests.exceptions.ConnectionError("my-reason"),
                    retry.TransientError,
                    lambda e: "my-reason" in str(e.exception),
                ),
            ],
        )
        def test_translates_azure_err_to_normal_err(
            self,
            mock_responses: RequestsMock,
            example_file: Path,
            response: MockResponseOrException,
            expected_errtype: type[Exception],
            check_err: Callable[[Exception], bool],
        ):
            mock_responses.add_callback(
                "PUT", "https://example.com/foo/bar/baz", Mock(return_value=response)
            )
            with pytest.raises(expected_errtype) as e:
                internal.InternalApi().upload_file(
                    "https://example.com/foo/bar/baz",
                    example_file.open("rb"),
                    extra_headers=self.MAGIC_HEADERS,
                )

            assert check_err(e.value), e.value


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
    api = internal.InternalApi()

    if expected_error:
        with pytest.raises(Exception, match="Some random error"):
            api._server_supports(feature)
    else:
        result = api._server_supports(feature)
        assert result == expected_result


def test_construct_use_artifact_query_with_every_field(mocker: MockerFixture):
    # Create mock internal API instance
    api = internal.InternalApi()

    mocker.patch.object(api, "settings", side_effect=lambda x: "default-" + x)

    # Simulate server support for ALL known features
    mock_server_features = dict.fromkeys(
        chain(ServerFeature.keys(), ServerFeature.values()),
        True,
    )
    mocker.patch.object(api, "_server_features", return_value=mock_server_features)

    test_cases = [
        {
            "entity_name": "test-entity",
            "project_name": "test-project",
            "run_name": "test-run",
            "artifact_id": "test-artifact-id",
            "use_as": "test-use-as",
            "artifact_entity_name": "test-artifact-entity",
            "artifact_project_name": "test-artifact-project",
        },
        {
            "entity_name": None,
            "project_name": None,
            "run_name": None,
            "artifact_id": "test-artifact-id",
            "use_as": None,
            "artifact_entity_name": "test-artifact-entity",
            "artifact_project_name": "test-artifact-project",
        },
    ]

    for case in test_cases:
        query, variables = api._construct_use_artifact_query(
            entity_name=case["entity_name"],
            project_name=case["project_name"],
            run_name=case["run_name"],
            artifact_id=case["artifact_id"],
            use_as=case["use_as"],
            artifact_entity_name=case["artifact_entity_name"],
            artifact_project_name=case["artifact_project_name"],
        )

        # Verify variables are correctly set
        expected_variables = {
            "entityName": case["entity_name"] or "default-entity",
            "projectName": case["project_name"] or "default-project",
            "runName": case["run_name"],
            "artifactID": case["artifact_id"],
            "usedAs": case["use_as"],
            "artifactEntityName": case["artifact_entity_name"],
            "artifactProjectName": case["artifact_project_name"],
        }
        assert variables == expected_variables

        query_str = str(query)
        assert "artifactEntityName" in query_str
        assert "artifactProjectName" in query_str
        if case["use_as"]:
            assert "usedAs" in query_str
        else:
            assert "usedAs" not in query_str


def test_construct_use_artifact_query_without_entity_project():
    # Test when server doesn't support entity/project information
    api = internal.InternalApi()
    api.settings = Mock(side_effect=lambda x: "default-" + x)

    # Mock methods to return False for entity/project support
    api._server_features = Mock(return_value={})

    query, variables = api._construct_use_artifact_query(
        entity_name="test-entity",
        project_name="test-project",
        run_name="test-run",
        artifact_id="test-artifact-id",
        use_as="test-use-as",
        artifact_entity_name="test-artifact-entity",
        artifact_project_name="test-artifact-project",
    )
    query_str = str(query)

    # Verify entity/project information is not in variables
    assert "artifactEntityName" not in variables
    assert "artifactProjectName" not in variables
    assert "artifactEntityName" not in query_str
    assert "artifactProjectName" not in query_str


def test_construct_use_artifact_query_without_used_as():
    # Test when no use_as value is provided.
    api = internal.InternalApi()
    api.settings = Mock(side_effect=lambda x: "default-" + x)

    # Simulate server support for ALL known features
    mock_server_features = dict.fromkeys(
        chain(ServerFeature.keys(), ServerFeature.values()),
        True,
    )
    api._server_features = Mock(return_value=mock_server_features)

    query, variables = api._construct_use_artifact_query(
        entity_name="test-entity",
        project_name="test-project",
        run_name="test-run",
        artifact_id="test-artifact-id",
        use_as=None,
        artifact_entity_name="test-artifact-entity",
        artifact_project_name="test-artifact-project",
    )
    query_str = str(query)

    # Verify usedAs is still in variables but not in query.
    assert "usedAs" in variables
    assert "usedAs:" not in query_str


class TestJWTAuth:
    def test_jwt_auth_sets_bearer_header(
        self, tmp_path: pathlib.Path, mocker: MockerFixture
    ):
        token_file = tmp_path / "token.jwt"
        token_file.write_text("test.jwt.token")

        mocker.patch(
            "wandb.sdk.lib.wbauth.AuthIdentityTokenFile.fetch_access_token",
            return_value="test_access_token_12345",
        )

        environ = {"WANDB_IDENTITY_TOKEN_FILE": str(token_file)}
        api = internal.InternalApi(environ=environ)

        assert "Authorization" in api._extra_http_headers
        assert (
            api._extra_http_headers["Authorization"] == "Bearer test_access_token_12345"
        )

    def test_api_key_takes_precedence_over_jwt(
        self, tmp_path: pathlib.Path, mocker: MockerFixture
    ):
        token_file = tmp_path / "token.jwt"
        token_file.write_text("test.jwt.token")

        fetch_mock = mocker.patch(
            "wandb.sdk.lib.wbauth.AuthIdentityTokenFile.fetch_access_token",
            return_value="test_access_token",
        )

        environ = {"WANDB_IDENTITY_TOKEN_FILE": str(token_file)}
        api = internal.InternalApi(
            default_settings={"api_key": "a" * 40},
            environ=environ,
        )

        fetch_mock.assert_not_called()
        assert api.request_auth == ("api", "a" * 40)

    def test_access_token_returns_none_without_token_file(self):
        api = internal.InternalApi(environ={})
        assert api.access_token is None

    def test_access_token_raises_for_missing_file(self, tmp_path: pathlib.Path):
        missing_file = tmp_path / "nonexistent.jwt"
        environ = {"WANDB_IDENTITY_TOKEN_FILE": str(missing_file)}

        with pytest.raises(wandb.errors.AuthenticationError, match="not found"):
            internal.InternalApi(environ=environ)
