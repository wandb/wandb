from wandb._pydantic import CompatBaseModel
from wandb.apis.public import ArtifactCollection, Project
from wandb.automations import ArtifactCollectionScope, ProjectScope, ScopeType
from wandb.automations._generated import TriggerScopeType
from wandb.automations.scopes import ArtifactCollectionScopeTypes, AutomationScope


class HasScope(CompatBaseModel):
    scope: AutomationScope


class HasCollectionScope(HasScope):
    scope: ArtifactCollectionScope


class HasProjectScope(HasScope):
    scope: ProjectScope


def test_public_scope_type_enum_is_subset_of_generated():
    """Check that the public `ScopeType` enum is a subset of the schema-generated enum.

    This is a safeguard in case we've had to make any extra customizations
    (e.g. renaming members) to the public API definition.
    """
    public_enum_values = {e.value for e in ScopeType}
    generated_enum_values = {e.value for e in TriggerScopeType}
    assert public_enum_values.issubset(generated_enum_values)


def test_scope_can_validate_from_wandb_artifact_collection(
    artifact_collection: ArtifactCollection,
):
    """Check that we can parse an automation scope from a pre-existing `ArtifactCollection` type."""

    validated = HasCollectionScope(scope=artifact_collection)
    validated_scope = validated.scope

    # ArtifactCollectionScope is defined as a Union type, so isinstance() checks won't work
    # prior to python 3.10.  We need to check against a tuple of the unioned types.
    # See:
    # - https://docs.python.org/3/library/stdtypes.html#union-type
    # - https://peps.python.org/pep-0604/

    assert isinstance(validated_scope, ArtifactCollectionScopeTypes)
    assert validated_scope.scope_type == ScopeType.ARTIFACT_COLLECTION
    assert validated_scope.id == artifact_collection.id
    assert validated_scope.name == artifact_collection.name

    validated = HasScope(scope=artifact_collection)
    validated_scope = validated.scope

    assert isinstance(validated_scope, ArtifactCollectionScopeTypes)
    assert validated_scope.scope_type == ScopeType.ARTIFACT_COLLECTION
    assert validated_scope.id == artifact_collection.id
    assert validated_scope.name == artifact_collection.name


def test_scope_can_validate_from_wandb_project(
    project: Project,
):
    """Check that we can parse an automation scope from a pre-existing `Project` type."""

    validated = HasProjectScope(scope=project)
    validated_scope = validated.scope

    assert isinstance(validated_scope, ProjectScope)
    assert validated_scope.scope_type == ScopeType.PROJECT
    assert validated_scope.id == project.id
    assert validated_scope.name == project.name

    validated = HasScope(scope=project)
    validated_scope = validated.scope

    assert isinstance(validated_scope, ProjectScope)
    assert validated_scope.scope_type == ScopeType.PROJECT
    assert validated_scope.id == project.id
    assert validated_scope.name == project.name
