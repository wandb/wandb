from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from wandb_gql import gql

import wandb
from wandb._analytics import tracked
from wandb.proto.wandb_internal_pb2 import ServerFeature
from wandb.sdk.artifacts._validators import REGISTRY_PREFIX, validate_project_name
from wandb.sdk.internal.internal_api import Api as InternalApi
from wandb.sdk.projects._generated import (
    DELETE_PROJECT_GQL,
    FETCH_REGISTRY_GQL,
    RENAME_PROJECT_GQL,
    UPSERT_REGISTRY_PROJECT_GQL,
    DeleteProject,
    RenameProject,
    UpsertRegistryProject,
)

from ._freezable_list import AddOnlyArtifactTypesList
from ._utils import (
    fetch_org_entity_from_organization,
    format_gql_artifact_types_input,
    gql_to_registry_visibility,
    registry_visibility_to_gql,
)
from .registries_search import Collections, Versions

if TYPE_CHECKING:
    from wandb_gql import Client


class Registry:
    """A single registry in the Registry."""

    def __init__(
        self,
        client: Client,
        organization: str,
        entity: str,
        name: str,
        attrs: dict[str, Any] | None = None,
    ):
        self.client = client
        self._name = name
        self._saved_name = name
        self._entity = entity
        self._organization = organization
        if attrs is not None:
            self._update_attributes(attrs)

    def _update_attributes(self, attrs: dict[str, Any]) -> None:
        """Helper method to update instance attributes from a dictionary."""
        self._id = attrs.get("id", "")
        if self._id is None:
            raise ValueError(f"Registry {self.name}'s id is not found")

        self._description = attrs.get("description", "")
        self._allow_all_artifact_types = attrs.get(
            "allowAllArtifactTypesInRegistry", False
        )
        self._artifact_types = AddOnlyArtifactTypesList(
            t["node"]["name"] for t in attrs.get("artifactTypes", {}).get("edges", [])
        )
        self._created_at = attrs.get("createdAt", "")
        self._updated_at = attrs.get("updatedAt", "")
        self._visibility = gql_to_registry_visibility(attrs.get("access", ""))

    @property
    def full_name(self) -> str:
        """Full name of the registry including the `wandb-registry-` prefix."""
        return f"wandb-registry-{self.name}"

    @property
    def name(self) -> str:
        """Name of the registry without the `wandb-registry-` prefix."""
        return self._name

    @name.setter
    def name(self, value: str):
        self._name = value

    @property
    def entity(self) -> str:
        """Organization entity of the registry."""
        return self._entity

    @property
    def organization(self) -> str:
        """Organization name of the registry."""
        return self._organization

    @property
    def description(self) -> str:
        """Description of the registry."""
        return self._description

    @description.setter
    def description(self, value: str):
        """Set the description of the registry."""
        self._description = value

    @property
    def allow_all_artifact_types(self):
        """Returns whether all artifact types are allowed in the registry.

        If `True` then artifacts of any type can be added to this registry.
        If `False` then artifacts are restricted to the types in `artifact_types` for this registry.
        """
        return self._allow_all_artifact_types

    @allow_all_artifact_types.setter
    def allow_all_artifact_types(self, value: bool):
        """Set whether all artifact types are allowed in the registry."""
        self._allow_all_artifact_types = value

    @property
    def artifact_types(self) -> AddOnlyArtifactTypesList:
        """Returns the artifact types allowed in the registry.

        If `allow_all_artifact_types` is `True` then `artifact_types` reflects the
        types previously saved or currently used in the registry.
        If `allow_all_artifact_types` is `False` then artifacts are restricted to the
        types in `artifact_types`.

        Note:
            Previously saved artifact types cannot be removed.

        Example:
        ```python
        import wandb

        registry = wandb.Api().create_registry()
        registry.artifact_types.append("model")
        registry.save()  # once saved, the artifact type `model` cannot be removed
        registry.artifact_types.append("accidentally_added")
        registry.artifact_types.remove(
            "accidentally_added"
        )  # Types can only be removed if it has not been saved yet
        ```
        """
        return self._artifact_types

    @property
    def created_at(self) -> str:
        """Timestamp of when the registry was created."""
        return self._created_at

    @property
    def updated_at(self) -> str:
        """Timestamp of when the registry was last updated."""
        return self._updated_at

    @property
    def path(self):
        return [self.entity, self.full_name]

    @property
    def visibility(self) -> Literal["organization", "restricted"]:
        """Visibility of the registry.

        Returns:
            Literal["organization", "restricted"]: The visibility level.
                - "organization": Anyone in the organization can view this registry.
                  You can edit their roles later from the settings in the UI.
                - "restricted": Only invited members via the UI can access this registry.
                  Public sharing is disabled.
        """
        return self._visibility

    @visibility.setter
    def visibility(self, value: Literal["organization", "restricted"]):
        """Set the visibility of the registry.

        Args:
            value: The visibility level. Options are:
                - "organization": Anyone in the organization can view this registry.
                  You can edit their roles later from the settings in the UI.
                - "restricted": Only invited members via the UI can access this registry.
                  Public sharing is disabled.
        """
        self._visibility = value

    @tracked
    def collections(self, filter: dict[str, Any] | None = None) -> Collections:
        """Returns the collections belonging to the registry."""
        registry_filter = {
            "name": self.full_name,
        }
        return Collections(self.client, self.organization, registry_filter, filter)

    @tracked
    def versions(self, filter: dict[str, Any] | None = None) -> Versions:
        """Returns the versions belonging to the registry."""
        registry_filter = {
            "name": self.full_name,
        }
        return Versions(self.client, self.organization, registry_filter, None, filter)

    @classmethod
    @tracked
    def create(
        cls,
        client: Client,
        organization: str,
        name: str,
        visibility: Literal["organization", "restricted"],
        description: str | None = None,
        artifact_types: list[str] | None = None,
    ):
        """Create a new registry.

        The registry name must be unique within the organization.
        This function should be called using `api.create_registry()`

        Args:
            client: The GraphQL client.
            organization: The name of the organization.
            name: The name of the registry (without the `wandb-registry-` prefix).
            visibility: The visibility level ('organization' or 'restricted').
            description: An optional description for the registry.
            artifact_types: An optional list of allowed artifact types.

        Returns:
            Registry: The newly created Registry object.

        Raises:
            ValueError: If a registry with the same name already exists in the
                organization or if the creation fails.
        """
        org_entity = fetch_org_entity_from_organization(client, organization)
        full_name = REGISTRY_PREFIX + name
        validate_project_name(full_name)
        accepted_artifact_types = []
        if artifact_types:
            accepted_artifact_types = format_gql_artifact_types_input(artifact_types)
        visibility_value = registry_visibility_to_gql(visibility)
        registry_creation_error = (
            f"Failed to create registry {name!r} in organization {organization!r}."
        )
        try:
            response = client.execute(
                gql(UPSERT_REGISTRY_PROJECT_GQL),
                variable_values={
                    "description": description,
                    "entityName": org_entity,
                    "name": full_name,
                    "access": visibility_value,
                    "allowAllArtifactTypesInRegistry": not accepted_artifact_types,
                    "artifactTypes": accepted_artifact_types,
                },
            )
        except Exception:
            raise ValueError(registry_creation_error)
        if not response["upsertModel"]["inserted"]:
            raise ValueError(registry_creation_error)

        return Registry(
            client,
            organization,
            org_entity,
            name,
            response["upsertModel"]["project"],
        )

    @tracked
    def delete(self) -> None:
        """Delete the registry. This is irreversible."""
        try:
            response = self.client.execute(
                gql(DELETE_PROJECT_GQL), variable_values={"id": self._id}
            )
            result = DeleteProject.model_validate(response)
        except Exception:
            raise ValueError(
                f"Failed to delete registry: {self.name!r} in organization: {self.organization!r}"
            )
        if not result.delete_model.success:
            raise ValueError(
                f"Failed to delete registry: {self.name!r} in organization: {self.organization!r}"
            )

    @tracked
    def load(self) -> None:
        """Load the registry attributes from the backend to reflect the latest saved state."""
        load_failure_message = (
            f"Failed to load registry {self.name!r} "
            f"in organization {self.organization!r}."
        )
        try:
            response = self.client.execute(
                gql(FETCH_REGISTRY_GQL),
                variable_values={
                    "name": self.full_name,
                    "entityName": self.entity,
                },
            )
        except Exception:
            raise ValueError(load_failure_message)
        if response["entity"] is None:
            raise ValueError(load_failure_message)
        self.attrs = response["entity"]["project"]
        if self.attrs is None:
            raise ValueError(load_failure_message)
        self._update_attributes(self.attrs)

    @tracked
    def save(self) -> None:
        """Save registry attributes to the backend."""
        if not InternalApi()._server_supports(
            ServerFeature.INCLUDE_ARTIFACT_TYPES_IN_REGISTRY_CREATION
        ):
            raise RuntimeError(
                "saving the registry is not enabled on this wandb server version. "
                "Please upgrade your server version or contact support at support@wandb.com."
            )

        if self._no_updating_registry_types():
            raise ValueError(
                f"Cannot update artifact types when `allows_all_artifact_types` is {True!r}. Set it to {False!r} first."
            )

        validate_project_name(self.full_name)
        visibility_value = registry_visibility_to_gql(self.visibility)
        newly_added_types = format_gql_artifact_types_input(self.artifact_types.draft)
        registry_save_error = f"Failed to save and update registry: {self.name} in organization: {self.organization}"
        full_saved_name = f"{REGISTRY_PREFIX}{self._saved_name}"
        try:
            response = self.client.execute(
                gql(UPSERT_REGISTRY_PROJECT_GQL),
                variable_values={
                    "description": self.description,
                    "entityName": self.entity,
                    "name": full_saved_name,  # this makes it so we are updating the original registry in case the name has changed
                    "access": visibility_value,
                    "allowAllArtifactTypesInRegistry": self.allow_all_artifact_types,
                    "artifactTypes": newly_added_types,
                },
            )
            result = UpsertRegistryProject.model_validate(response)
        except Exception:
            raise ValueError(registry_save_error)
        if result.upsert_model.inserted:
            # This is not suppose trigger unless the user has messed with the `_saved_name` variable
            wandb.termlog(
                f"Created registry {self.name!r} in organization {self.organization!r} on save"
            )
        self._update_attributes(response["upsertModel"]["project"])

        # Update the name of the registry if it has changed
        if self._saved_name != self.name:
            response = self.client.execute(
                gql(RENAME_PROJECT_GQL),
                variable_values={
                    "entityName": self.entity,
                    "oldProjectName": full_saved_name,
                    "newProjectName": self.full_name,
                },
            )
            result = RenameProject.model_validate(response)
            self._saved_name = self.name
            if result.rename_project.inserted:
                # This is not suppose trigger unless the user has messed with the `_saved_name` variable
                wandb.termlog(f"Created new registry {self.name!r} on save")

    def _no_updating_registry_types(self) -> bool:
        # artifact types draft means user assigned types to add that are not yet saved
        return len(self.artifact_types.draft) > 0 and self.allow_all_artifact_types
