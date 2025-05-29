import sys
from unittest import mock
import wandb
from wandb import Api
from wandb.apis.public.reports import BetaReport

print("=== Test with from_path method ===")
with mock.patch.object(wandb, "login", mock.MagicMock()):
    path = "test/test/reports/My-Report--XYZ"
    report = Api().from_path(path)

    print("id:", report.id)
    print("name:", report.name)
    print("display_name:", report.display_name)
    print("description:", report.description)
    print("user:", report.user)
    print("created_at:", report.created_at)
    print("updated_at:", report.updated_at)

    report_html = report.to_html(hidden=True)
    print("to_html works:", "test/test/reports/My-Report--XYZ" in report_html)

print("\n=== Test with full GraphQL response ===")
attrs = {
    "id": "test-id",
    "name": "Test Report",
    "displayName": "Test Display Name",
    "description": "Test Description",
    "user": {"username": "testuser", "email": "test@example.com"},
    "spec": "{}",
    "updatedAt": "2023-01-01T00:00:00Z",
    "createdAt": "2023-01-01T00:00:00Z"
}

report = BetaReport(None, attrs, "test-entity", "test-project")

print("All properties with full data:")
print("id:", report.id)
print("name:", report.name)
print("display_name:", report.display_name)
print("description:", report.description)
print("user:", report.user)
print("created_at:", report.created_at)
print("updated_at:", report.updated_at)
