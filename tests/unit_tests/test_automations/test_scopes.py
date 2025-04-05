from wandb.apis.public import ArtifactCollection, Project
from wandb.automations import ArtifactCollectionScope, ProjectScope


def test_scope_can_validate_from_wandb_artifact_collection(
    artifact_collection: ArtifactCollection,
):
    validated_scope = ArtifactCollectionScope.model_validate(artifact_collection)
    assert isinstance(validated_scope, ArtifactCollectionScope)
    assert validated_scope.id == artifact_collection.id
    assert validated_scope.name == artifact_collection.name


def test_scope_can_validate_from_wandb_project(
    project: Project,
):
    validated_scope = ProjectScope.model_validate(project)
    assert isinstance(validated_scope, ProjectScope)
    assert validated_scope.id == project.id
    assert validated_scope.name == project.name
