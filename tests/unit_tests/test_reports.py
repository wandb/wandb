import json
from unittest import mock

import pytest
import wandb
from wandb import Api
from wandb.apis.public.reports import BetaReport


@pytest.mark.usefixtures("patch_apikey", "patch_prompt", "skip_verify_login")
def test_report_properties_from_path():
    """Test that BetaReport properties work correctly when created via from_path."""
    path = "test/test/reports/My-Report--XYZ"
    with mock.patch.object(wandb, "login", mock.MagicMock()):
        report = Api().from_path(path)

        assert report.id is not None
        assert isinstance(report.name, (str, type(None)))
        assert isinstance(report.display_name, (str, type(None)))
        assert isinstance(report.description, (str, type(None)))
        assert isinstance(report.user, (dict, type(None)))
        assert isinstance(report.spec, (dict, type(None)))
        assert isinstance(report.updated_at, (str, type(None)))
        assert isinstance(report.created_at, (str, type(None)))
        assert isinstance(report.url, (str, type(None)))


@pytest.mark.usefixtures("patch_apikey", "patch_prompt")
def test_report_properties_full():
    """Test that BetaReport properties work correctly with a complete set of attributes."""
    # Mock the client with app_url
    mock_client = mock.MagicMock()
    mock_client.app_url = "https://wandb.ai/"

    attrs = {
        "id": "test-id",
        "name": "Test Report",
        "displayName": "Test Display Name",
        "description": "Test Description",
        "user": {"username": "testuser", "email": "test@example.com"},
        "spec": json.dumps({"panels": []}),
        "updatedAt": "2023-01-01T00:00:00Z",
        "createdAt": "2023-01-01T00:00:00Z",
    }

    report = BetaReport(mock_client, attrs, "test-entity", "test-project")

    assert report.id == "test-id"
    assert report.name == "Test Report"
    assert report.display_name == "Test Display Name"
    assert report.description == "Test Description"
    assert report.user == {"username": "testuser", "email": "test@example.com"}
    assert report.spec == {"panels": []}
    assert report.updated_at == "2023-01-01T00:00:00Z"
    assert report.created_at == "2023-01-01T00:00:00Z"
    assert (
        report.url
        == "https://wandb.ai/test-entity/test-project/reports/Test-Display-Name--test-id"
    )


@pytest.mark.usefixtures("patch_apikey", "patch_prompt")
def test_report_properties_missing_attributes():
    """Test that BetaReport properties handle missing attributes gracefully."""
    attrs = {
        "id": "test-id",
        "displayName": "Test Display Name",
    }

    report = BetaReport(None, attrs, "test-entity", "test-project")

    assert report.id == "test-id"
    assert report.display_name == "Test Display Name"
    assert report.name is None
    assert report.description is None
    assert report.user is None
    assert report.spec == {}
    assert report.updated_at is None
    assert report.created_at is None


@pytest.mark.usefixtures("patch_apikey", "patch_prompt")
def test_report_user_property_access():
    """Test that user property provides access to username and email."""
    attrs = {
        "id": "test-id",
        "user": {"username": "testuser", "email": "test@example.com"},
    }

    report = BetaReport(None, attrs, "test-entity", "test-project")

    assert report.user["username"] == "testuser"
    assert report.user["email"] == "test@example.com"


@pytest.mark.usefixtures("patch_apikey", "patch_prompt")
def test_report_user_property_missing():
    """Test that user property handles missing user data gracefully."""
    attrs = {
        "id": "test-id",
    }

    report = BetaReport(None, attrs, "test-entity", "test-project")

    assert report.user is None


@pytest.mark.usefixtures("patch_apikey", "patch_prompt")
def test_report_url_creation():
    """Test that url creation handles display names with symbols."""
    # Mock the client with app_url
    mock_client = mock.MagicMock()
    mock_client.app_url = "https://wandb.ai/"
    test_entity = "test-entity"
    test_project = "test-project"
    attrs = {
        "id": "test-id",
        "displayName": "Test Timestamp (25/05/01 09:28:29)",
    }

    report = BetaReport(mock_client, attrs, test_entity, test_project)

    assert (
        report.url
        == f"https://wandb.ai/{test_entity}/{test_project}/reports/Test-Timestamp-25-05-01-09-28-29--test-id"
    )
