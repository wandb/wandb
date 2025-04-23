import pytest
from wandb import Api
from wandb.sdk.artifacts._validators import REGISTRY_PREFIX


def test_registry_create_edit(user_and_org):
    """Tests the basic CRUD operations for a registry."""
    organization = user_and_org.organization_name
    api = Api()
    registry_name = "test"
    initial_description = "Initial registry description."
    updated_description = "Updated registry description."
    artifact_type_1 = "model-1"

    # TODO: Setting visibility to restricted is giving permission errors.
    # Need to dig into backend code to figure out why as local testing works fine.
    registry = api.create_registry(
        name=registry_name,
        visibility="organization",
        organization=organization,
        description=initial_description,
        accepted_artifact_types=None,  # Test default: allow all
    )

    assert registry is not None
    assert registry.name == registry_name
    assert registry.full_name == f"{REGISTRY_PREFIX}{registry_name}"
    assert registry.organization == organization
    assert registry.description == initial_description
    assert registry.visibility == "organization"
    assert registry.allow_all_artifact_types
    assert len(registry.artifact_types) == 0

    # This doesn't do anything but want to make sure it doesn't raise unexpected errors
    # as users can call load() on a registry whenever they want
    registry.load()
    assert registry.name == registry_name
    assert registry.description == initial_description
    assert registry.visibility == "organization"
    assert registry.allow_all_artifact_types

    # === Edit ===
    registry.description = updated_description
    registry.allow_all_artifact_types = False
    registry.artifact_types.append(artifact_type_1)
    registry.save()

    fetched_registry = api.registry(registry_name, organization)
    assert fetched_registry
    assert fetched_registry.description == updated_description
    assert fetched_registry.allow_all_artifact_types is False
    assert artifact_type_1 in fetched_registry.artifact_types


def test_delete_registry(user_and_org):
    """Tests the ability to delete a registry."""
    api = Api()
    organization = user_and_org.organization_name
    registry_name = "test"

    api.create_registry(
        organization=organization,
        name=registry_name,
        visibility="organization",
        description="Test registry",
    )
    registry = api.registry(registry_name, organization)
    assert registry

    registry.delete()

    with pytest.raises(ValueError, match="Failed to load registry"):
        registry.load()

    # Try to delete again, should fail
    with pytest.raises(
        ValueError,
        match="Failed to delete registry",
    ):
        registry.delete()


def test_registry_create_edit_artifact_types(user_and_org):
    """Tests the ability to create, edit, and delete artifact types in a registry."""
    organization = user_and_org.organization_name
    api = Api()
    artifact_type_1 = "model-1"
    artifact_type_2 = "model-2"
    registry_name = "test"
    registry = api.create_registry(
        organization=organization,
        name=registry_name,
        visibility="organization",
        accepted_artifact_types=None,  # Test default: allow all
    )
    assert registry
    assert registry.allow_all_artifact_types
    assert list(registry.artifact_types) == []

    # Test restriction: Cannot add types if allow_all is True
    registry.artifact_types.append(artifact_type_1)
    with pytest.raises(ValueError, match="Cannot update registry artifact types"):
        registry.save()
    # Reset for valid save
    registry.allow_all_artifact_types = False
    registry.save()
    assert list(registry.artifact_types) == [artifact_type_1]
    assert list(registry.artifact_types.draft) == []

    # Add a second type
    registry.artifact_types.append(artifact_type_2)
    assert list(registry.artifact_types.draft) == [artifact_type_2]
    assert artifact_type_1 in registry.artifact_types
    registry.save()
    assert list(registry.artifact_types) == [artifact_type_1, artifact_type_2]
    assert list(registry.artifact_types.draft) == []

    # try to remove a type that has been saved
    with pytest.raises(ValueError, match="Cannot remove artifact type"):
        registry.artifact_types.remove(artifact_type_1)


def test_registry_create_duplicate_name(user_and_org):
    """Tests that creating a registry with a duplicate name fails."""
    organization = user_and_org.organization_name
    api = Api()
    registry_name = "test"

    # Create the first registry
    registry = api.create_registry(
        organization=organization,
        name=registry_name,
        visibility="organization",
        description="First registry",
    )
    assert registry

    # Attempt to create another registry with the same name
    # Note error is generic to avoid leaking permission information
    with pytest.raises(ValueError, match="Failed to create registry"):
        api.create_registry(
            organization=organization,
            name=registry_name,
            visibility="organization",
            description="Duplicate registry",
        )


def test_infer_organization_from_create_load(user_and_org):
    """Tests that the organization is inferred from the create and load methods."""
    # This user only belongs to one organization, so we can test that the organization is inferred
    organization = user_and_org.organization_name
    api = Api()
    registry_name = "test"
    registry = api.create_registry(
        name=registry_name,
        visibility="organization",
    )
    assert registry

    fetched_registry = api.registry(registry_name)
    assert fetched_registry
    assert fetched_registry.organization == organization


def test_input_invalid_organizations(user_and_org):
    """Tests that the organization is inferred from the create and load methods."""
    organization = user_and_org.organization_name
    api = Api()
    registry_name = "test"
    with pytest.raises(ValueError, match="Error fetching org entity for organization"):
        api.create_registry(
            name=registry_name,
            visibility="organization",
            organization=organization + "wrong_organization",
        )

    with pytest.raises(ValueError, match="Error fetching org entity for organization"):
        api.registry(registry_name, organization + "wrong_organization")


def test_user_in_multiple_orgs(user_and_2_orgs):
    """Tests that the organization is inferred from the create and load methods."""
    user_org1, user_org2 = user_and_2_orgs
    api = Api()
    registry_name = "test"

    # user belongs to 2 orgs, so they have to specify which one they want to create the registry in
    with pytest.raises(ValueError, match="Multiple organizations found for entity."):
        api.create_registry(
            name=registry_name,
            visibility="organization",
        )

    registry_org1 = api.create_registry(
        name=registry_name,
        visibility="organization",
        organization=user_org1.organization_name,
    )
    assert registry_org1
    assert registry_org1.organization == user_org1.organization_name

    registry_org2 = api.create_registry(
        name=registry_name,
        visibility="organization",
        organization=user_org2.organization_name,
    )
    assert registry_org2
    assert registry_org2.organization == user_org2.organization_name


def test_invalid_artifact_type_input(user_and_org):
    """Tests that the organization is inferred from the create and load methods."""
    organization = user_and_org.organization_name
    api = Api()
    registry_name = "test"
    with pytest.raises(ValueError, match="Artifact types must not contain any of the"):
        api.create_registry(
            organization=organization,
            name=registry_name,
            visibility="organization",
            accepted_artifact_types=["::///"],
        )

    registry = api.create_registry(
        organization=organization,
        name=registry_name,
        visibility="organization",
        accepted_artifact_types=["normal"],
    )

    registry.artifact_types.append("::///")
    with pytest.raises(ValueError, match="Artifact types must not contain any of the"):
        registry.save()
