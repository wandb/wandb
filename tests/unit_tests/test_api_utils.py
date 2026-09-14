from types import SimpleNamespace

import pytest
from wandb.apis.public.utils import (
    fetch_org_from_settings_or_entity,
    parse_org_from_registry_path,
)


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
def org_info_from_entity(monkeypatch):
    infos = {
        "team-entity": SimpleNamespace(
            organization=SimpleNamespace(name="team-org"), user=None
        ),
        "default-entity": SimpleNamespace(
            organization=None,
            user=SimpleNamespace(organizations=[SimpleNamespace(name="default-org")]),
        ),
    }
    monkeypatch.setattr(
        "wandb.apis.public.utils.org_info_from_entity",
        lambda service_api, entity: infos[entity],
    )


def test_fetch_org_from_settings_direct(org_info_from_entity):
    """Test when organization is directly specified in settings"""
    settings = {"organization": "org-display", "entity": "default-entity"}
    result = fetch_org_from_settings_or_entity(None, settings)
    assert result == "org-display"


def test_fetch_org_from_entity(org_info_from_entity):
    """Test fetching org when only entity is available"""
    settings = {"organization": None, "entity": "team-entity"}
    result = fetch_org_from_settings_or_entity(None, settings)
    assert result == "team-org"


def test_fetch_org_from_default_entity(org_info_from_entity):
    """Test fetching org using default entity when settings entity is None"""
    settings = {"organization": None, "entity": None}
    result = fetch_org_from_settings_or_entity(
        None, settings, default_entity="default-entity"
    )
    assert result == "default-org"


def test_no_entity_raises_error(org_info_from_entity):
    """Test that error is raised when no entity is available"""
    settings = {"organization": None, "entity": None}
    with pytest.raises(ValueError, match="No entity specified"):
        fetch_org_from_settings_or_entity(None, settings)
