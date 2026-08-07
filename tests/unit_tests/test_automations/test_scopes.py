from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ValidationError
from pytest import mark, raises
from wandb._strutils import nameof
from wandb.automations import (
    ArtifactCollectionScope,
    EntityScope,
    ProjectScope,
    RegistryScope,
    ScopeType,
)
from wandb.automations._generated import ProjectScopeFields, TriggerScopeType
from wandb.automations.scopes import AutomationScope
from wandb.sdk.artifacts._validators import REGISTRY_PREFIX

if TYPE_CHECKING:
    from unittest.mock import Mock

    from wandb.apis.public import (
        ArtifactCollection,
        Organization,
        Project,
        Registry,
        Team,
    )


class HasScope(BaseModel):
    scope: AutomationScope


class HasCollectionScope(HasScope):
    scope: ArtifactCollectionScope


class HasProjectScope(HasScope):
    scope: ProjectScope


class HasRegistryScope(HasScope):
    scope: RegistryScope


class HasEntityScope(HasScope):
    scope: EntityScope


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

    assert validated.scope.scope_type is ScopeType.ARTIFACT_COLLECTION
    assert validated.scope.id == artifact_collection.id
    assert validated.scope.name == artifact_collection.name


@mark.parametrize("model_cls", (HasProjectScope, HasScope), ids=nameof)
def test_scope_can_validate_from_wandb_project(
    project: Project, model_cls: type[HasScope]
):
    """Check that we can parse an automation scope from a pre-existing `Project` type."""

    validated = model_cls(scope=project)
    assert validated.scope.scope_type is ScopeType.PROJECT
    assert validated.scope.is_registry is False
    assert validated.scope.id == project.id
    assert validated.scope.name == project.name


@mark.parametrize("model_cls", (HasRegistryScope, HasScope), ids=nameof)
def test_scope_can_validate_from_wandb_registry(
    registry: Registry, model_cls: type[HasScope]
):
    """Check that we can parse an automation scope from a pre-existing `Registry` type."""

    validated = model_cls(scope=registry)
    assert validated.scope.scope_type is ScopeType.PROJECT
    assert validated.scope.is_registry is True
    assert validated.scope.id == registry.id
    assert validated.scope.name == registry.full_name


@mark.parametrize(
    ("name", "expected_type", "expected_is_registry"),
    (
        ("test-project", ProjectScope, False),
        (REGISTRY_PREFIX, ProjectScope, False),
        (f"{REGISTRY_PREFIX}test", RegistryScope, True),
    ),
    ids=("project", "bare-prefix", "registry"),
)
def test_project_scope_fragment_sets_registry_discriminator(
    project: Project,
    name: str,
    expected_type: type[ProjectScope],
    expected_is_registry: bool,
):
    fragment = ProjectScopeFields(id=project.id, name=name)

    validated = HasScope(scope=fragment)
    assert type(validated.scope) is expected_type
    assert validated.scope.is_registry is expected_is_registry


@mark.parametrize("model_cls", (HasEntityScope, HasScope), ids=nameof)
def test_scope_can_validate_from_wandb_team(team: Team, model_cls: type[HasScope]):
    """Check that we can parse an automation scope from a pre-existing `Team` (team entity)."""

    validated = model_cls(scope=team)
    assert validated.scope.scope_type is ScopeType.ENTITY
    assert validated.scope.entity_type == "team"
    assert validated.scope.id == team.id
    assert validated.scope.name == team.name


@mark.parametrize("model_cls", (HasEntityScope, HasScope), ids=nameof)
def test_scope_can_validate_from_wandb_org(
    org: Organization, model_cls: type[HasScope]
):
    """Check that an org-scoped automation scope resolves to the org's (non-team) entity."""

    # The org's entity is inferred from the org on any field that accepts an entity scope.
    # The actual org entity can also be passed directly (it would be weird if this didn't work).
    for scope_arg in (org, org.org_entity):
        validated = model_cls(scope=scope_arg)
        assert validated.scope.scope_type is ScopeType.ENTITY
        assert validated.scope.entity_type == "organization"
        assert validated.scope.id == org.org_entity.id
        assert validated.scope.name == org.org_entity.name


def test_entity_scope_uses_entity_type_as_discriminator():
    team_entity_data = {
        "__typename": "Entity",
        "id": "Entity:1",
        "name": "team-entity",
        "entityType": "team",
    }
    org_entity_data = {
        "__typename": "Entity",
        "id": "Entity:2",
        "name": "org-entity",
        "entityType": "organization",
    }
    team_scope = HasEntityScope(scope=team_entity_data).scope
    org_scope = HasEntityScope(scope=org_entity_data).scope

    assert team_scope.entity_type == "team"
    assert org_scope.entity_type == "organization"


@mark.parametrize("model_cls", (HasEntityScope, HasScope), ids=nameof)
def test_personal_entity_scope_is_not_allowed(model_cls: type[HasScope]):
    personal_entity_data = {
        "__typename": "Entity",
        "id": "Entity:1",
        "name": "personal-entity",
        "entityType": "personal",
    }

    with raises(ValidationError):
        model_cls(scope=personal_entity_data)


def test_organization_uses_org_entity_type_as_discriminator(mock_client: Mock):
    from wandb.apis.public import Organization

    org_data = {
        "id": "Organization:1",
        "name": "test-org",
        "orgEntity": {
            "__typename": "Entity",
            "id": "Entity:1",
            "name": "test-org",
            "entityType": "organization",
        },
    }
    org = Organization(mock_client, **org_data)
    assert org.org_entity.entity_type == "organization"

    entity_scope = HasEntityScope(scope=org).scope
    assert entity_scope.entity_type == "organization"
