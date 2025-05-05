from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional

from wandb_gql import gql

import wandb
from wandb.apis.public.registries._freezable_list import AddOnlyArtifactTypesList
from wandb.apis.public.registries.registries_search import Collections, Versions
from wandb.apis.public.registries.utils import (
    _fetch_org_entity_from_organization,
    _format_gql_artifact_types_input,
    _gql_to_registry_visibility,
    _registry_visibility_to_gql,
)
from wandb.sdk.artifacts._graphql_fragments import _gql_registry_fragment
from wandb.sdk.artifacts._validators import REGISTRY_PREFIX

if TYPE_CHECKING:
    from wandb_gql import Client


class Registry:
    """A single registry in the Registry."""

    UPSERT_REGISTRY_PROJECT = gql(
        """
            mutation UpsertRegistryProject(
                $description: String,
                $entityName: String,
                $name: String,
                $access: String,
                $allowAllArtifactTypesInRegistry: Boolean,
                $artifactTypes: [ArtifactTypeInput!]
            ) {
                upsertModel(
                    input: {
                        description: $description,
                        entityName: $entityName,
                        name: $name, access: $access,
                        allowAllArtifactTypesInRegistry:
                        $allowAllArtifactTypesInRegistry,
                        artifactTypes: $artifactTypes
                    }
                ) {
                    project {
                        ...RegistryFragment
                    }
                    inserted
                }
            }
        """
        + _gql_registry_fragment()
    )

    def __init__(
        self,
        client: "Client",
        organization: str,
        entity: str,
        name: str,
        attrs: Optional[Dict[str, Any]] = None,
    ):
        self.client = client
        self._name = name
        self._entity = entity
        self._organization = organization
        if attrs is not None:
            self._update_attributes(attrs)

    def _update_attributes(self, attrs: Dict[str, Any]) -> None:
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
        self._visibility = _gql_to_registry_visibility(attrs.get("access", ""))

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

    def collections(self, filter: Optional[Dict[str, Any]] = None) -> Collections:
        """Returns the collections belonging to the registry."""
        registry_filter = {
            "name": self.full_name,
        }
        return Collections(self.client, self.organization, registry_filter, filter)

    def versions(self, filter: Optional[Dict[str, Any]] = None) -> Versions:
        """Returns the versions belonging to the registry."""
        registry_filter = {
            "name": self.full_name,
        }
        return Versions(self.client, self.organization, registry_filter, None, filter)

    @classmethod
    def create(
        cls,
        client: "Client",
        organization: str,
        name: str,
        visibility: Literal["organization", "restricted"],
        description: Optional[str] = None,
        artifact_types: Optional[List[str]] = None,
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
        org_entity = _fetch_org_entity_from_organization(client, organization)
        full_name = REGISTRY_PREFIX + name
        accepted_artifact_types = []
        if artifact_types:
            accepted_artifact_types = _format_gql_artifact_types_input(artifact_types)
        visibility_value = _registry_visibility_to_gql(visibility)
        registry_creation_error = (
            f"Failed to create registry {name} in organization {organization}."
        )
        try:
            response = client.execute(
                cls.UPSERT_REGISTRY_PROJECT,
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

    def delete(self) -> None:
        """Delete the registry. This is irreversible."""
        mutation = gql(
            """
            mutation deleteModel($id: String!) {
                deleteModel(input: {id: $id}) {
                    success
                    __typename
                }
            }
        """
        )
        try:
            self.client.execute(mutation, variable_values={"id": self._id})
        except Exception:
            raise ValueError(
                f"Failed to delete registry: {self.name} in organization: {self.organization}"
            )

    def load(self) -> None:
        """Load the registry attributes from the backend to reflect the latest saved state."""
        load_failure_message = (
            f"Failed to load registry '{self.name}' "
            f"in organization '{self.organization}'."
        )
        try:
            response = self.client.execute(
                gql(
                    """
                    query Registry($name: String, $entityName: String) {
                        entity(name: $entityName) {
                            project(name: $name) {
                                ...RegistryFragment
                            }
                        }
                    }
                """
                    + _gql_registry_fragment()
                ),
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

    def save(self) -> None:
        """Save registry attributes to the backend."""
        if self._no_updating_registry_types():
            raise ValueError(
                "Cannot update artifact types when `allows_all_artifact_types` is `true`. Set it to `false` first."
            )
        visibility_value = _registry_visibility_to_gql(self.visibility)
        newly_added_types = _format_gql_artifact_types_input(self.artifact_types.draft)
        registry_save_error = f"Failed to save and update registry: {self.name} in organization: {self.organization}"
        try:
            response = self.client.execute(
                self.UPSERT_REGISTRY_PROJECT,
                variable_values={
                    "description": self.description,
                    "entityName": self.entity,
                    "name": self.full_name,
                    "access": visibility_value,
                    "allowAllArtifactTypesInRegistry": self.allow_all_artifact_types,
                    "artifactTypes": newly_added_types,
                },
            )
        except Exception:
            raise ValueError(registry_save_error)
        if response["upsertModel"]["inserted"]:
            wandb.termlog(
                f"Created registry: {self.name} in organization: {self.organization} on save"
            )
        self._update_attributes(response["upsertModel"]["project"])

    def _no_updating_registry_types(self) -> bool:
        # artifact types draft means user assigned types to add that are not yet saved
        return len(self.artifact_types.draft) > 0 and self.allow_all_artifact_types
