from pydantic import BaseModel
from pytest import mark
from wandb._strutils import nameof
from wandb.apis.public import ArtifactCollection, Project
from wandb.automations import ArtifactCollectionScope, ProjectScope, ScopeType
from wandb.automations._generated import TriggerScopeType
from wandb.automations.scopes import ArtifactCollectionScopeTypes, AutomationScope


class HasScope(BaseModel):
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


@mark.parametrize("model_cls", (HasCollectionScope, HasScope), ids=nameof)
def test_scope_can_validate_from_wandb_artifact_collection(
    artifact_collection: ArtifactCollection,
    model_cls: type[HasScope],
):
    """Check that we can parse an automation scope from a pre-existing `ArtifactCollection` type."""

    validated = model_cls(scope=artifact_collection)

    # ArtifactCollectionScope is defined as a Union type, so isinstance() checks won't work
    # prior to python 3.10.  We need to check against a tuple of the unioned types.
    # See:
    # - https://docs.python.org/3/library/stdtypes.html#union-type
    # - https://peps.python.org/pep-0604/

    assert isinstance(validated.scope, ArtifactCollectionScopeTypes)
    assert validated.scope.scope_type == ScopeType.ARTIFACT_COLLECTION
    assert validated.scope.id == artifact_collection.id
    assert validated.scope.name == artifact_collection.name


@mark.parametrize("model_cls", (HasProjectScope, HasScope), ids=nameof)
def test_scope_can_validate_from_wandb_project(
    project: Project,
    model_cls: type[HasScope],
):
    """Check that we can parse an automation scope from a pre-existing `Project` type."""

    validated = model_cls(scope=project)
    assert isinstance(validated.scope, ProjectScope)
    assert validated.scope.scope_type == ScopeType.PROJECT
    assert validated.scope.id == project.id
    assert validated.scope.name == project.name
