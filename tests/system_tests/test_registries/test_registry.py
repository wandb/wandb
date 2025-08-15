from typing import Iterator
from unittest.mock import patch

import wandb
from pytest import fixture, mark, raises, skip
from wandb import Api, Artifact
from wandb.proto.wandb_internal_pb2 import ServerFeature
from wandb.sdk.artifacts._validators import REGISTRY_PREFIX
from wandb.sdk.internal.internal_api import Api as InternalApi


@fixture
def default_organization(user_in_orgs_factory) -> Iterator[str]:
    """Provides the name of the single default organization."""
    user_in_orgs = user_in_orgs_factory()
    yield user_in_orgs.organization_names[0]


@fixture
def skip_if_server_does_not_support_create_registry() -> None:
    """Skips the test for older server versions that do not support Api.create_registry()."""
    if not InternalApi()._server_supports(
        ServerFeature.INCLUDE_ARTIFACT_TYPES_IN_REGISTRY_CREATION
    ):
        skip("Cannot create a test registry on this server version.")


@mark.usefixtures(skip_if_server_does_not_support_create_registry.__name__)
def test_registry_create_edit(default_organization, api: Api):
    """Tests the basic CRUD operations for a registry."""
    registry_name = "test"
    initial_description = "Initial registry description."
    updated_description = "Updated registry description."
    artifact_type_1 = "model-1"

    # TODO: Setting visibility to restricted is giving permission errors.
    # Need to dig into backend code to figure out why. Local testing works fine.
    registry = api.create_registry(
        name=registry_name,
        visibility="organization",
        organization=default_organization,
        description=initial_description,
        artifact_types=None,  # Test default: allow all
    )

    assert registry is not None
    assert registry.name == registry_name
    assert registry.full_name == f"{REGISTRY_PREFIX}{registry_name}"
    assert registry.organization == default_organization
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

    fetched_registry = api.registry(registry_name, default_organization)
    assert fetched_registry
    assert fetched_registry.description == updated_description
    assert fetched_registry.allow_all_artifact_types is False
    assert artifact_type_1 in fetched_registry.artifact_types


@mark.usefixtures(skip_if_server_does_not_support_create_registry.__name__)
def test_delete_registry(default_organization, api: Api):
    """Tests the ability to delete a registry."""
    registry_name = "test"

    api.create_registry(
        organization=default_organization,
        name=registry_name,
        visibility="organization",
        description="Test registry",
    )
    registry = api.registry(registry_name, default_organization)
    assert registry

    registry.delete()

    with raises(ValueError, match="Failed to load registry"):
        registry.load()

    # Try to delete again, should fail
    with raises(
        ValueError,
        match="Failed to delete registry",
    ):
        registry.delete()


@mark.usefixtures(skip_if_server_does_not_support_create_registry.__name__)
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
    assert registry.allow_all_artifact_types
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


@mark.usefixtures(skip_if_server_does_not_support_create_registry.__name__)
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


@mark.usefixtures(skip_if_server_does_not_support_create_registry.__name__)
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


@mark.usefixtures(skip_if_server_does_not_support_create_registry.__name__)
def test_input_invalid_organizations(default_organization, api: Api):
    """Tests that invalid organization inputs raise errors."""
    bad_org_name = f"{default_organization}_wrong_organization"

    registry_name = "test"
    with raises(
        ValueError,
        match=f"Organization entity for {bad_org_name} not found.",
    ):
        api.create_registry(
            name=registry_name,
            visibility="organization",
            organization=bad_org_name,
        )

    with raises(
        ValueError,
        match=f"Organization entity for {bad_org_name} not found.",
    ):
        api.registry(registry_name, f"{default_organization}_wrong_organization")


@mark.usefixtures(skip_if_server_does_not_support_create_registry.__name__)
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


@mark.usefixtures(skip_if_server_does_not_support_create_registry.__name__)
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


@mark.usefixtures(skip_if_server_does_not_support_create_registry.__name__)
def test_create_registry_invalid_visibility_input(default_organization, api: Api):
    registry_name = "test"
    with raises(ValueError, match="Invalid visibility"):
        api.create_registry(
            organization=default_organization,
            name=registry_name,
            visibility="invalid",
        )


@mark.usefixtures(skip_if_server_does_not_support_create_registry.__name__)
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


@mark.usefixtures(skip_if_server_does_not_support_create_registry.__name__)
@patch("wandb.apis.public.registries.registry.wandb.termlog")
def test_edit_registry_name(mock_termlog, default_organization, api: Api):
    registry_name = "test"
    registry = api.create_registry(
        organization=default_organization,
        name=registry_name,
        visibility="organization",
        description="This is the initial description",
    )

    new_registry_name = "new-name"
    registry.name = new_registry_name
    assert registry._saved_name == registry_name
    registry.save()
    assert registry.name == new_registry_name
    assert registry._saved_name == new_registry_name
    assert registry.description == "This is the initial description"

    # Double check we didn't create a new registry instead of renaming the old one
    with raises(ValueError, match="Failed to load registry"):
        api.registry(registry_name, default_organization)

    new_name_registry = api.registry(new_registry_name, default_organization)
    assert new_name_registry
    assert new_name_registry.description == "This is the initial description"
    # Assert that the rename termlog was called as we never created a new registry
    mock_termlog.assert_not_called()


@mark.usefixtures(skip_if_server_does_not_support_create_registry.__name__)
def test_fetch_registries(team: str, org: str, api: Api):
    num_registries = 3

    for registry_idx in range(num_registries):
        api.create_registry(
            organization=org,
            name=f"test-{registry_idx}",
            visibility="organization",
        )

    registries = list(api.registries(organization=org))

    assert len(registries) == num_registries


@mark.usefixtures(skip_if_server_does_not_support_create_registry.__name__)
def test_registries_collections(team: str, org: str, api: Api):
    registry_name = "test-registry"
    registry = api.create_registry(
        organization=org,
        name=registry_name,
        visibility="organization",
    )

    num_versions = 3

    # Each version linked to a different registry collection
    with wandb.init(entity=team) as run:
        for i in range(num_versions):
            artifact = Artifact(name=f"test-artifact-{i}", type="test-type")
            run.log_artifact(artifact)

            target_path = f"{org}/{registry.full_name}/reg-collection-{i}"
            artifact.link(target_path)

    registries = api.registries(organization=org)

    collections = sorted(registries.collections(), key=lambda c: c.name)
    assert len(collections) == num_versions

    # Check that we have the correct registry collections
    for i, collection in enumerate(collections):
        assert collection.name == f"reg-collection-{i}"
        assert collection.type == "test-type"


@mark.usefixtures(skip_if_server_does_not_support_create_registry.__name__)
def test_registries_versions(team: str, org: str, api: Api):
    registry_name = "test-registry"
    registry = api.create_registry(
        organization=org,
        name=registry_name,
        visibility="organization",
    )

    num_versions = 3

    # Each version linked to the same registry collection
    with wandb.init(entity=team) as run:
        for i in range(num_versions):
            artifact = Artifact(name=f"test-artifact-{i}", type="test-type")
            run.log_artifact(artifact)

            target_path = f"{org}/{registry.full_name}/reg-collection"
            artifact.link(target_path)

    registries = api.registries(organization=org)

    versions = sorted(registries.versions(), key=lambda v: v.name)
    assert len(versions) == num_versions

    # Check that the versions are linked to the correct registry collection
    for i, registry_version in enumerate(versions):
        assert registry_version.source_name == f"test-artifact-{i}:v0"
        assert registry_version.name == f"reg-collection:v{i}"
