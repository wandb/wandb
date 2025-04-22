from typing import TYPE_CHECKING, Any, Dict, Literal, Optional

from wandb_gql import gql

import wandb
from wandb.apis.public.registries._freezable_list import AddOnlyArtifactTypesList
from wandb.apis.public.registries.registries_search import (
    Collections,
    Registries,
    Versions,
)
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
            mutation UpsertRegistryProject($description: String, $entityName: String, $name: String, $access: String, $allowAllArtifactTypesInRegistry: Boolean, $artifactTypes: [ArtifactTypeInput!]) {
            upsertModel(
                input: {description: $description, entityName: $entityName, name: $name, access: $access, allowAllArtifactTypesInRegistry: $allowAllArtifactTypesInRegistry, artifactTypes: $artifactTypes}
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
        self._full_name = f"wandb-registry-{name}"
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
    def full_name(self):
        return self._full_name

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, value: str):
        self._name = value

    @property
    def entity(self):
        return self._entity

    @property
    def organization(self):
        return self._organization

    @property
    def description(self):
        return self._description

    @description.setter
    def description(self, value: str):
        self._description = value

    @property
    def allow_all_artifact_types(self):
        return self._allow_all_artifact_types

    @allow_all_artifact_types.setter
    def allow_all_artifact_types(self, value: bool):
        self._allow_all_artifact_types = value

    @property
    def artifact_types(self) -> AddOnlyArtifactTypesList:
        return self._artifact_types

    @property
    def created_at(self):
        return self._created_at

    @property
    def updated_at(self):
        return self._updated_at

    @property
    def path(self):
        return [self.entity, self.full_name]

    @property
    def visibility(self):
        return self._visibility

    def collections(self, filter: Optional[Dict[str, Any]] = None):
        registry_filter = {
            "name": self.full_name,
        }
        return Collections(self.client, self.organization, registry_filter, filter)

    def versions(self, filter: Optional[Dict[str, Any]] = None):
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
        accepted_artifact_types: Optional[list[str]] = None,
    ):
        existing_registry = Registries(client, organization, {"name": name})
        if existing_registry:
            raise ValueError(
                f"Registry {name} already exists in organization {organization}, please use a different name."
            )

        org_entity = _fetch_org_entity_from_organization(client, organization)
        full_name = REGISTRY_PREFIX + name
        artifact_types = _format_gql_artifact_types_input(accepted_artifact_types)
        visibility_value = _registry_visibility_to_gql(visibility)
        registry_creation_error = (
            """Failed to create registry {name} in organization {organization}."""
        )
        try:
            response = client.execute(
                cls.UPSERT_REGISTRY_PROJECT,
                variable_values={
                    "description": description,
                    "entityName": org_entity,
                    "name": full_name,
                    "access": visibility_value,
                    "allowAllArtifactTypesInRegistry": accepted_artifact_types is None,
                    "artifactTypes": artifact_types,
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

    def delete(self):
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
        self.client.execute(mutation, variable_values={"id": self._id})

    def load(self):
        load_failure_message = (
            f"Could not load registry: {self.name} in organization: {self.organization}"
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

    def save(self):
        if self._no_updating_registry_types():
            raise ValueError(
                "Cannot update registry types if registry `allows_all_artifact_types` is `true`, please set `allow_all_artifact_types` to `false` if you want to update registry types."
            )
        visibility_value = _registry_visibility_to_gql(self.visibility)
        artifact_types = _format_gql_artifact_types_input(self.artifact_types)
        registry_save_error = f"Failed to update registry: {self.name} in organization: {self.organization}"
        try:
            response = self.client.execute(
                self.UPSERT_REGISTRY_PROJECT,
                variable_values={
                    "description": self.description,
                    "entityName": self.entity,
                    "name": self.full_name,
                    "access": visibility_value,
                    "allowAllArtifactTypesInRegistry": self.allow_all_artifact_types,
                    "artifactTypes": artifact_types,
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
