from __future__ import annotations

from typing import Callable, Iterator
from unittest.mock import patch

import wandb
from pytest import fixture, mark, param, raises
from wandb import Api, Artifact, Registry
from wandb._strutils import b64decode_ascii
from wandb.sdk.artifacts._validators import REGISTRY_PREFIX


@fixture
def default_organization(user_in_orgs_factory) -> Iterator[str]:
    """Provides the name of the single default organization."""
    user_in_orgs = user_in_orgs_factory()
    yield user_in_orgs.organization_names[0]


@mark.parametrize(
    "orig_description",
    [
        param(None, id="null"),
        param("", id="empty string"),
        param("Original registry description.", id="non-empty string"),
    ],
)
def test_registry_create_edit(
    default_organization: str,
    make_registry: Callable[..., Registry],
    api: Api,
    orig_description: str | None,
):
    """Tests the basic CRUD operations for a registry."""
    registry_name = "test"
    new_description = "New registry description."
    artifact_type_1 = "model-1"

    # TODO: Setting visibility to restricted is giving permission errors.
    # Need to dig into backend code to figure out why. Local testing works fine.
    registry = make_registry(
        name=registry_name,
        visibility="organization",
        organization=default_organization,
        description=orig_description,
        artifact_types=None,  # Test default: allow all
    )

    assert registry is not None

    registry_id = registry.id
    assert b64decode_ascii(registry_id).startswith("Project:")

    assert registry.name == registry_name
    assert registry.full_name == f"{REGISTRY_PREFIX}{registry_name}"
    assert registry.organization == default_organization
    assert registry.description == orig_description
    assert registry.visibility == "organization"
    assert registry.allow_all_artifact_types is True
    assert len(registry.artifact_types) == 0

    # This doesn't do anything but want to make sure it doesn't raise unexpected errors
    # as users can call load() on a registry whenever they want
    registry.load()
    assert registry.id == registry_id
    assert registry.name == registry_name
    assert registry.description == orig_description
    assert registry.visibility == "organization"
    assert registry.allow_all_artifact_types is True

    # === Edit ===
    registry.description = new_description
    registry.allow_all_artifact_types = False
    registry.artifact_types.append(artifact_type_1)
    registry.save()

    fetched_registry = api.registry(registry_name, default_organization)
    assert fetched_registry
    assert fetched_registry.id == registry_id
    assert fetched_registry.description == new_description
    assert fetched_registry.allow_all_artifact_types is False
    assert artifact_type_1 in fetched_registry.artifact_types

    # Registry ID should be read-only
    with raises(AttributeError):
        fetched_registry.id = "new-id"
    fetched_registry.save()
    assert api.registry(registry_name, default_organization).id == registry_id


def test_delete_registry(default_organization, make_registry, api: Api):
    """Tests the ability to delete a registry."""
    registry_name = "test"

    make_registry(
        organization=default_organization,
        name=registry_name,
        visibility="organization",
        description="Test registry",
    )
    registry = api.registry(registry_name, default_organization)

    registry.delete()

    with raises(ValueError, match="Failed to load registry"):
        registry.load()

    # Try to delete again, should fail
    with raises(ValueError, match="Failed to delete registry"):
        registry.delete()


@mark.usefixtures("skip_if_server_does_not_support_create_registry")
def test_registry_create_edit_artifact_types(default_organization, api: Api):
    """Tests the ability to create, edit, and delete artifact types in a registry."""
    artifact_type_1 = "model-1"
    artifact_type_2 = "model-2"
    registry_name = "test"
    registry = api.create_registry(
        organization=default_organization,
        name=registry_name,
        visibility="organization",
        artifact_types=None,  # Test default: allow all
    )
    assert registry
    assert registry.allow_all_artifact_types is True
    assert registry.artifact_types == []

    # Test restriction: Cannot add types if allow_all is True
    registry.artifact_types.append(artifact_type_1)
    with raises(
        ValueError,
        match="Cannot update artifact types when `allows_all_artifact_types` is True. Set it to False first.",
    ):
        registry.save()
    # Reset for valid save
    registry.allow_all_artifact_types = False
    assert registry.allow_all_artifact_types is False
    registry.save()
    assert registry.artifact_types == [artifact_type_1]
    assert registry.artifact_types.draft == ()

    # Add a second type
    registry.artifact_types.append(artifact_type_2)
    assert registry.artifact_types.draft == (artifact_type_2,)
    assert artifact_type_1 in registry.artifact_types
    registry.save()
    # After saving the types returned back might be in a different order
    assert set(registry.artifact_types) == {artifact_type_1, artifact_type_2}
    assert registry.artifact_types.draft == ()

    # try to remove a type that has been saved
    with raises(
        ValueError,
        match="Cannot remove artifact type",
    ):
        registry.artifact_types.remove(artifact_type_1)


@mark.usefixtures("skip_if_server_does_not_support_create_registry")
def test_registry_create_duplicate_name(default_organization, api: Api):
    """Tests that creating a registry with a duplicate name fails."""
    registry_name = "test"

    # Create the first registry
    registry = api.create_registry(
        organization=default_organization,
        name=registry_name,
        visibility="organization",
        description="First registry",
    )
    assert registry

    # Attempt to create another registry with the same name
    # Note error is generic to avoid leaking permission information
    with raises(ValueError, match="please use a different name"):
        api.create_registry(
            organization=default_organization,
            name=registry_name,
            visibility="organization",
            description="Duplicate registry",
        )


@mark.usefixtures("skip_if_server_does_not_support_create_registry")
def test_registry_create_empty_name(default_organization, api: Api):
    """Tests that creating a registry with an empty name fails."""
    with raises(ValueError):
        api.create_registry(
            organization=default_organization,
            name="",
            visibility="organization",
            description="Registry with empty name",
        )


@mark.usefixtures("skip_if_server_does_not_support_create_registry")
def test_infer_organization_from_create_load(default_organization, api: Api):
    """Tests that the organization is inferred from the create and load methods."""
    # This user only belongs to one organization, so we can test that the organization is inferred
    registry_name = "test"
    registry = api.create_registry(
        name=registry_name,
        visibility="organization",
    )
    assert registry

    fetched_registry = api.registry(registry_name)
    assert fetched_registry
    assert fetched_registry.organization == default_organization


@mark.usefixtures("skip_if_server_does_not_support_create_registry")
def test_input_invalid_organizations(default_organization, api: Api):
    """Tests that invalid organization inputs raise errors."""
    bad_org_name = f"{default_organization}_wrong_organization"

    registry_name = "test"
    with raises(
        ValueError,
        match=f"Organization entity for {bad_org_name!r} not found.",
    ):
        api.create_registry(
            name=registry_name,
            visibility="organization",
            organization=bad_org_name,
        )

    with raises(
        ValueError,
        match=f"Organization entity for {bad_org_name!r} not found.",
    ):
        api.registry(registry_name, f"{default_organization}_wrong_organization")


@mark.usefixtures("skip_if_server_does_not_support_create_registry")
def test_user_in_multiple_orgs(user_in_orgs_factory, api: Api):
    """Tests that the organization is inferred from the create and load methods."""
    user_in_orgs = user_in_orgs_factory(number_of_orgs=2)
    organizations = user_in_orgs.organization_names

    assert len(organizations) == 2

    org1, org2 = organizations

    registry_name = "test"

    # user belongs to 2 orgs, so they have to specify which one they want to create the registry in
    with raises(ValueError, match="Multiple organizations found for entity."):
        api.create_registry(
            name=registry_name,
            visibility="organization",
        )

    registry_org1 = api.create_registry(
        name=registry_name,
        visibility="organization",
        organization=org1,
    )
    assert registry_org1
    assert registry_org1.organization == org1

    registry_org2 = api.create_registry(
        name=registry_name,
        visibility="organization",
        organization=org2,
    )
    assert registry_org2
    assert registry_org2.organization == org2


@mark.usefixtures("skip_if_server_does_not_support_create_registry")
def test_invalid_artifact_type_input(default_organization, api: Api):
    registry_name = "test"
    with raises(ValueError, match="Artifact types must not contain any of the"):
        api.create_registry(
            organization=default_organization,
            name=registry_name,
            visibility="organization",
            artifact_types=["::///"],
        )

    registry = api.create_registry(
        organization=default_organization,
        name=registry_name,
        visibility="organization",
        artifact_types=["normal"],
    )

    registry.artifact_types.append("::///")
    with raises(ValueError, match="Artifact types must not contain any of the"):
        registry.save()


@mark.usefixtures("skip_if_server_does_not_support_create_registry")
def test_create_registry_invalid_visibility_input(default_organization, api: Api):
    registry_name = "test"
    with raises(ValueError, match="Invalid visibility"):
        api.create_registry(
            organization=default_organization,
            name=registry_name,
            visibility="invalid",
        )


@mark.usefixtures("skip_if_server_does_not_support_create_registry")
def test_create_registry_invalid_registry_name(default_organization, api: Api):
    registry_name = "::::????"
    with raises(ValueError, match="Invalid project/registry name"):
        api.create_registry(
            organization=default_organization,
            name=registry_name,
            visibility="invalid",
        )

    registry = api.create_registry(
        organization=default_organization,
        name="test",
        visibility="organization",
    )
    assert registry
    registry.name = "p" * 200
    with raises(ValueError, match="must be 113 characters or less"):
        registry.save()


@mark.usefixtures("skip_if_server_does_not_support_create_registry")
@patch("wandb.apis.public.registries.registry.wandb.termlog")
def test_edit_registry_name(mock_termlog, default_organization, api: Api):
    registry_name = "test"
    registry = api.create_registry(
        organization=default_organization,
        name=registry_name,
        visibility="organization",
        description="This is the initial description",
    )

    assert registry.name == registry_name

    new_registry_name = "new-name"

    registry.name = new_registry_name
    assert registry.name == new_registry_name

    registry.save()

    assert registry.name == new_registry_name
    assert registry.description == "This is the initial description"

    # Double check we didn't create a new registry instead of renaming the old one
    with raises(ValueError, match="Failed to load registry"):
        api.registry(registry_name, default_organization)

    new_name_registry = api.registry(new_registry_name, default_organization)
    assert new_name_registry
    assert new_name_registry.description == "This is the initial description"
    # Assert that the rename termlog was called as we never created a new registry
    mock_termlog.assert_not_called()


@mark.usefixtures("skip_if_server_does_not_support_create_registry")
def test_fetch_registries(team: str, org: str, org_entity: str, api: Api):
    num_registries = 3

    for registry_idx in range(num_registries):
        api.create_registry(
            organization=org,
            name=f"test-{registry_idx}",
            visibility="organization",
        )

    # Sort the registries by name for predictable assertions
    registries = sorted(api.registries(organization=org), key=lambda r: r.name)

    assert len(registries) == num_registries

    for i, registry in enumerate(registries):
        assert registry.entity == org_entity
        assert registry.organization == org
        assert registry.full_name == f"wandb-registry-test-{i}"
        assert registry.full_name == f"{REGISTRY_PREFIX}test-{i}"
        assert registry.visibility == "organization"


@fixture
def source_artifacts(team: str):
    """Test source artifacts with distinct names."""
    count = 3

    artifacts = [Artifact(f"test-artifact-{i}", type="test-type") for i in range(count)]
    with wandb.init(entity=team) as run:
        return [run.log_artifact(art) for art in artifacts]


@fixture
def target_registry(make_registry, org: str):
    """A test registry to be populated with collections and linked artifacts."""
    return make_registry(
        organization=org, name="test-registry", visibility="organization"
    )


def test_registries_collections(
    org: str, api: Api, source_artifacts: list[Artifact], target_registry: Registry
):
    # Each version linked to a different registry collection
    for i, artifact in enumerate(source_artifacts):
        artifact.link(f"{org}/{target_registry.full_name}/reg-collection-{i}")

    registries = api.registries(organization=org)

    collections = sorted(registries.collections(), key=lambda c: c.name)
    assert len(collections) == len(source_artifacts)

    # Check that we have the correct registry collections
    for i, collection in enumerate(collections):
        assert collection.name == f"reg-collection-{i}"
        assert collection.type == "test-type"


def test_registries_versions(
    org: str,
    org_entity: str,
    team: str,
    api: Api,
    source_artifacts: list[Artifact],
    target_registry: Registry,
):
    # Each version linked to the same registry collection
    for artifact in source_artifacts:
        artifact.link(f"{org}/{target_registry.full_name}/reg-collection")

    registries = api.registries(organization=org)

    versions = sorted(registries.versions(), key=lambda v: v.name)
    assert len(versions) == len(source_artifacts)

    # Sanity check: all source artifacts were logged from the same project
    source_projects = list(set(src.project for src in source_artifacts))
    assert len(source_projects) == 1
    source_project = source_projects[0]

    # Check that the versions are linked to the correct registry collection
    for i, registry_version in enumerate(versions):
        assert registry_version.source_name == f"test-artifact-{i}:v0"
        assert registry_version.source_project == source_project
        assert registry_version.source_entity == team
        assert registry_version.source_version == "v0"

        assert registry_version.name == f"reg-collection:v{i}"
        assert registry_version.project == target_registry.full_name
        assert registry_version.entity == org_entity
        assert registry_version.version == f"v{i}"

        if i == len(versions) - 1:
            assert registry_version.aliases == ["latest"]
        else:
            assert registry_version.aliases == []
