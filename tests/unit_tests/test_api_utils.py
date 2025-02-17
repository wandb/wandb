from unittest.mock import patch

import pytest
from wandb.apis.public.utils import (
    check_server_feature,
    fetch_org_from_settings_or_entity,
    parse_org_from_registry_path,
)
from wandb.proto.v3.wandb_internal_pb2 import ServerFeature
from wandb.sdk.internal.internal_api import _OrgNames


@pytest.mark.parametrize(
    "path, path_type, expected",
    [
        # Valid cases
        ("my-org/wandb-registry-model", "project", "my-org"),
        ("my-org/wandb-registry-model/model:v1", "artifact", "my-org"),
        # Invalid cases
        ("", "project", ""),  # empty path
        ("", "artifact", ""),  # empty path
        ("my-org/myproject", "project", ""),  # not a Registry project
        ("my-org/myproject/model", "artifact", ""),  # not a Registry project
        # No orgs set in artifact paths
        ("model", "artifact", ""),
        ("wandb-registry-model/model", "artifact", ""),
        # No orgs set in project path
        ("wandb-registry-model", "project", ""),
    ],
)
def test_parse_org_from_registry_path(path, path_type, expected):
    """Test parse_org_from_registry_path with various input combinations."""
    result = parse_org_from_registry_path(path, path_type)
    assert result == expected


@pytest.fixture
def mock_fetch_orgs_and_org_entities_from_entity(monkeypatch):
    def mock_fetch_orgs(self, entity_name):
        responses = {
            "team-entity": [
                _OrgNames(entity_name="team-entity", display_name="team-org")
            ],
            "default-entity": [
                _OrgNames(entity_name="default-entity", display_name="default-org")
            ],
            "multi-org-user-entity": [
                _OrgNames(entity_name="org1", display_name="Org 1"),
                _OrgNames(entity_name="org2", display_name="Org 2"),
            ],
        }
        return responses.get(entity_name, [])

    monkeypatch.setattr(
        "wandb.sdk.internal.internal_api.Api._fetch_orgs_and_org_entities_from_entity",
        mock_fetch_orgs,
    )


def test_fetch_org_from_settings_direct(mock_fetch_orgs_and_org_entities_from_entity):
    """Test when organization is directly specified in settings"""
    settings = {"organization": "org-display", "entity": "default-entity"}
    result = fetch_org_from_settings_or_entity(settings)
    assert result == "org-display"


def test_fetch_org_from_entity(mock_fetch_orgs_and_org_entities_from_entity):
    """Test fetching org when only entity is available"""
    settings = {"organization": None, "entity": "team-entity"}
    result = fetch_org_from_settings_or_entity(settings)
    assert result == "team-org"


def test_fetch_org_from_default_entity(mock_fetch_orgs_and_org_entities_from_entity):
    """Test fetching org using default entity when settings entity is None"""
    settings = {"organization": None, "entity": None}
    result = fetch_org_from_settings_or_entity(
        settings, default_entity="default-entity"
    )
    assert result == "default-org"


def test_no_entity_raises_error(mock_fetch_orgs_and_org_entities_from_entity):
    """Test that error is raised when no entity is available"""
    settings = {"organization": None, "entity": None}
    with pytest.raises(ValueError, match="No entity specified"):
        fetch_org_from_settings_or_entity(settings)


def test_no_orgs_found_raises_error(mock_fetch_orgs_and_org_entities_from_entity):
    """Test that error is raised when no orgs are found for entity"""
    settings = {"organization": None, "entity": "random-entity-possibly-not-real"}
    with pytest.raises(ValueError, match="No organizations found for entity"):
        fetch_org_from_settings_or_entity(settings)


def test_multiple_orgs_raises_error(mock_fetch_orgs_and_org_entities_from_entity):
    """Test that error is raised when multiple orgs are found for entity"""
    settings = {"organization": None, "entity": "multi-org-user-entity"}
    with pytest.raises(ValueError, match="Multiple organizations found for entity"):
        fetch_org_from_settings_or_entity(settings)


ENABLED_FEATURE_RESPONSE = {
    "serverInfo": {
        "features": [
            {"name": "LARGE_FILENAMES", "isEnabled": True},
            {"name": "ARTIFACT_TAGS", "isEnabled": False},
        ]
    }
}

NO_FEATURES_RESPONSE = {"serverInfo": {"features": []}}


@pytest.fixture
def mock_client():
    with patch("wandb_gql.Client") as mock:
        mock.return_value = None
        yield mock


def test_feature_enabled(mock_client):
    mock_client.execute.return_value = ENABLED_FEATURE_RESPONSE
    result = check_server_feature(mock_client, ServerFeature.LARGE_FILENAMES)

    assert result


def test_feature_disabled(mock_client):
    mock_client.execute.return_value = ENABLED_FEATURE_RESPONSE
    result = check_server_feature(mock_client, ServerFeature.ARTIFACT_TAGS)

    assert result is False


def test_feature_not_in_response(mock_client):
    mock_client.execute.return_value = ENABLED_FEATURE_RESPONSE
    result = check_server_feature(mock_client, ServerFeature.ARTIFACT_REGISTRY_SEARCH)

    assert result is False


def test_empty_features_list(mock_client):
    mock_client.execute.return_value = NO_FEATURES_RESPONSE
    result = check_server_feature(mock_client, ServerFeature.LARGE_FILENAMES)

    assert result is False


def test_server_not_supporting_features(mock_client):
    error_msg = 'Cannot query field "features" on type "ServerInfo".'
    mock_client.execute.side_effect = Exception(error_msg)

    result = check_server_feature(mock_client, ServerFeature.LARGE_FILENAMES)

    assert result is False


def test_other_server_error(mock_client):
    mock_client.execute.side_effect = Exception("Some other error")

    with pytest.raises(Exception, match="Some other error"):
        check_server_feature(mock_client, ServerFeature.LARGE_FILENAMES)
