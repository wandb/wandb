from typing import Any, Dict, Optional

from wandb_gql import Client

from wandb.apis.public.registries.registries_search import Collections, Versions
from wandb.sdk.artifacts._validators import REGISTRY_PREFIX


class Registry:
    """A single registry in the Registry."""

    def __init__(
        self,
        client: "Client",
        organization: str,
        entity: str,
        full_name: str,
        attrs: Dict[str, Any],
    ):
        self.client = client
        self._full_name = full_name
        self._name = full_name.replace(REGISTRY_PREFIX, "")
        self._entity = entity
        self._organization = organization
        self._description = attrs.get("description", "")
        self._allow_all_artifact_types = attrs.get(
            "allowAllArtifactTypesInRegistry", False
        )
        self._artifact_types = [
            t["node"]["name"] for t in attrs.get("artifactTypes", {}).get("edges", [])
        ]
        self._id = attrs.get("id", "")
        self._created_at = attrs.get("createdAt", "")
        self._updated_at = attrs.get("updatedAt", "")

    @property
    def full_name(self):
        return self._full_name

    @property
    def name(self):
        return self._name

    @property
    def entity(self):
        return self._entity

    @property
    def organization(self):
        return self._organization

    @property
    def description(self):
        return self._description

    @property
    def allow_all_artifact_types(self):
        return self._allow_all_artifact_types

    @property
    def artifact_types(self):
        return self._artifact_types

    @property
    def created_at(self):
        return self._created_at

    @property
    def updated_at(self):
        return self._updated_at

    @property
    def path(self):
        return [self.entity, self.name]

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
