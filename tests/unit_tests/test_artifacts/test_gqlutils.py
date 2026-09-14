from unittest.mock import Mock

import pytest
from wandb.sdk.artifacts._gqlutils import record_artifact_use


@pytest.mark.parametrize("server_takes_artifact_location", [True, False])
@pytest.mark.parametrize("use_as", ["test-use-as", None])
def test_record_artifact_use_query(server_takes_artifact_location, use_as):
    service_api = Mock()
    service_api.feature_enabled.return_value = server_takes_artifact_location
    service_api.execute_graphql.return_value = {
        "useArtifact": {"artifact": {"id": "test-artifact-id"}}
    }

    result = record_artifact_use(
        service_api,
        artifact_id="test-artifact-id",
        entity_name="test-entity",
        project_name="test-project",
        run_name="test-run",
        artifact_entity_name="test-artifact-entity",
        artifact_project_name="test-artifact-project",
        use_as=use_as,
    )

    assert result == {"id": "test-artifact-id"}
    query, variables = service_api.execute_graphql.call_args.args
    assert variables["entityName"] == "test-entity"
    assert variables["runName"] == "test-run"
    assert ("usedAs: $usedAs" in query) == (use_as is not None)
    assert ("artifactEntityName" in query) == server_takes_artifact_location
    assert ("artifactEntityName" in variables) == server_takes_artifact_location
