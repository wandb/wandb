from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import PositiveInt
from wandb_gql import gql

import wandb
from wandb._analytics import tracked
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.artifacts._generated import (
    DELETE_REGISTRY_GQL,
    FETCH_REGISTRY_GQL,
    RENAME_REGISTRY_GQL,
    UPSERT_REGISTRY_GQL,
    DeleteRegistry,
    FetchRegistry,
    RegistryFragment,
    RenameProjectInput,
    RenameRegistry,
    UpsertModelInput,
    UpsertRegistry,
)
from wandb.sdk.artifacts._gqlutils import server_supports
from wandb.sdk.artifacts._models import RegistryData
from wandb.sdk.artifacts._validators import REGISTRY_PREFIX, validate_project_name

from ._freezable_list import AddOnlyArtifactTypesList
from ._utils import (
    Visibility,
    fetch_org_entity_from_organization,
    prepare_artifact_types_input,
)
from .registries_search import Collections, Versions

if TYPE_CHECKING:
    from wandb_gql import Client


class Registry:
    """A single registry in the Registry."""

    _saved: RegistryData
    """The saved registry data as last fetched from the W&B server."""

    _current: RegistryData
    """The local, editable registry data."""

    def __init__(
        self,
        client: Client,
        organization: str,
        entity: str,
        name: str,
        attrs: RegistryFragment | None = None,
    ):
        self.client = client

        if attrs is None:
            # FIXME: This is awkward and bypasses validation which seems shaky.
            # Reconsider the init signature of `Registry` so this isn't necessary?
            draft = RegistryData.model_construct(
                organization=organization, entity=entity, name=name
            )
            self._saved = draft
            self._current = draft.model_copy(deep=True)
        else:
            self._update_attributes(attrs)

    def _update_attributes(self, fragment: RegistryFragment) -> None:
        """Internal helper method to update instance attributes from GraphQL fragment data."""
        saved = RegistryData.from_fragment(fragment)
        self._saved = saved
        self._current = saved.model_copy(deep=True)

    @property
    def full_name(self) -> str:
        """Full name of the registry including the `wandb-registry-` prefix."""
        return self._current.full_name

    @property
    def name(self) -> str:
        """Name of the registry without the `wandb-registry-` prefix."""
        return self._current.name

    @name.setter
    def name(self, value: str):
        self._current.name = value

    @property
    def entity(self) -> str:
        """Organization entity of the registry."""
        return self._current.entity

    @property
    def organization(self) -> str:
        """Organization name of the registry."""
        return self._current.organization

    @property
    def description(self) -> str:
        """Description of the registry."""
        return self._current.description

    @description.setter
    def description(self, value: str):
        """Set the description of the registry."""
        self._current.description = value

    @property
    def allow_all_artifact_types(self) -> bool:
        """Returns whether all artifact types are allowed in the registry.

        If `True` then artifacts of any type can be added to this registry.
        If `False` then artifacts are restricted to the types in `artifact_types` for this registry.
        """
        return self._current.allow_all_artifact_types

    @allow_all_artifact_types.setter
    def allow_all_artifact_types(self, value: bool) -> None:
        """Set whether all artifact types are allowed in the registry."""
        self._current.allow_all_artifact_types = value

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
        return self._current.artifact_types

    @property
    def created_at(self) -> str:
        """Timestamp of when the registry was created."""
        return self._current.created_at

    @property
    def updated_at(self) -> str:
        """Timestamp of when the registry was last updated."""
        return self._current.updated_at

    @property
    def path(self) -> list[str]:
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
        return self._current.visibility.name

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
        self._current.visibility = value

    @tracked
    def collections(
        self, filter: dict[str, Any] | None = None, per_page: PositiveInt = 100
    ) -> Collections:
        """Returns the collections belonging to the registry."""
        return Collections(
            client=self.client,
            organization=self.organization,
            registry_filter={"name": self.full_name},
            collection_filter=filter,
            per_page=per_page,
        )

    @tracked
    def versions(
        self, filter: dict[str, Any] | None = None, per_page: PositiveInt = 100
    ) -> Versions:
        """Returns the versions belonging to the registry."""
        return Versions(
            client=self.client,
            organization=self.organization,
            registry_filter={"name": self.full_name},
            collection_filter=None,
            artifact_filter=filter,
            per_page=per_page,
        )

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
        failed_msg = (
            f"Failed to create registry {name!r} in organization {organization!r}."
        )

        org_entity = fetch_org_entity_from_organization(client, organization)

        gql_op = gql(UPSERT_REGISTRY_GQL)
        gql_input = UpsertModelInput(
            description=description,
            entity_name=org_entity,
            name=validate_project_name(f"{REGISTRY_PREFIX}{name}"),
            access=Visibility.from_python(visibility).value,
            allow_all_artifact_types_in_registry=not artifact_types,
            artifact_types=prepare_artifact_types_input(artifact_types),
        )
        gql_vars = {"input": gql_input.model_dump()}
        try:
            data = client.execute(gql_op, variable_values=gql_vars)
            result = UpsertRegistry.model_validate(data).upsert_model
        except Exception as e:
            raise ValueError(failed_msg) from e
        if not (result and result.inserted and (registry_project := result.project)):
            raise ValueError(failed_msg)

        return Registry(
            client,
            organization=organization,
            entity=org_entity,
            name=name,
            attrs=registry_project,
        )

    @tracked
    def delete(self) -> None:
        """Delete the registry. This is irreversible."""
        failed_msg = f"Failed to delete registry {self.name!r} in organization {self.organization!r}"

        gql_op = gql(DELETE_REGISTRY_GQL)
        gql_vars = {"id": self._saved.id}
        try:
            data = self.client.execute(gql_op, variable_values=gql_vars)
            result = DeleteRegistry.model_validate(data).delete_model
        except Exception as e:
            raise ValueError(failed_msg) from e
        if not (result and result.success):
            raise ValueError(failed_msg)

    @tracked
    def load(self) -> None:
        """Load the registry attributes from the backend to reflect the latest saved state."""
        failed_msg = f"Failed to load registry {self.name!r} in organization {self.organization!r}."

        gql_op = gql(FETCH_REGISTRY_GQL)
        gql_vars = {"name": self.full_name, "entity": self.entity}
        try:
            data = self.client.execute(gql_op, variable_values=gql_vars)
            result = FetchRegistry.model_validate(data)
        except Exception as e:
            raise ValueError(failed_msg) from e

        if not ((entity := result.entity) and (registry_project := entity.project)):
            raise ValueError(failed_msg)

        self._update_attributes(registry_project)

    @tracked
    def save(self) -> None:
        """Save registry attributes to the backend."""
        if not server_supports(
            self.client, pb.INCLUDE_ARTIFACT_TYPES_IN_REGISTRY_CREATION
        ):
            raise RuntimeError(
                "Saving the registry is not enabled on this wandb server version. "
                "Please upgrade your server version or contact support at support@wandb.com."
            )

        # If `artifact_types.draft` has items, it means the user has added artifact types that aren't saved yet.
        if (
            new_artifact_types := self.artifact_types.draft
        ) and self.allow_all_artifact_types:
            raise ValueError(
                f"Cannot update artifact types when `allows_all_artifact_types` is {True!r}. Set it to {False!r} first."
            )

        failed_msg = f"Failed to save registry {self.name!r} in organization {self.organization!r}"

        old_project_name = validate_project_name(self._saved.full_name)
        new_project_name = validate_project_name(self._current.full_name)

        upsert_op = gql(UPSERT_REGISTRY_GQL)
        upsert_input = UpsertModelInput(
            description=self.description,
            entity_name=self.entity,
            name=old_project_name,
            access=self._current.visibility.value,
            allow_all_artifact_types_in_registry=self.allow_all_artifact_types,
            artifact_types=prepare_artifact_types_input(new_artifact_types),
        )
        upsert_vars = {"input": upsert_input.model_dump()}
        try:
            data = self.client.execute(upsert_op, variable_values=upsert_vars)
            result = UpsertRegistry.model_validate(data).upsert_model
        except Exception as e:
            raise ValueError(failed_msg) from e

        if result and result.inserted:
            # This is not suppose trigger unless the user has messed with the `_saved_name` variable
            wandb.termlog(
                f"Created registry {self.name!r} in organization {self.organization!r} on save"
            )

        if not (result and (registry_project := result.project)):
            raise ValueError(failed_msg)

        self._update_attributes(registry_project)

        # Update the name of the registry if it has changed
        if old_project_name != new_project_name:
            rename_op = gql(RENAME_REGISTRY_GQL)
            rename_input = RenameProjectInput(
                entity_name=self.entity,
                old_project_name=old_project_name,
                new_project_name=new_project_name,
            )
            rename_vars = {"input": rename_input.model_dump()}
            data = self.client.execute(rename_op, variable_values=rename_vars)
            result = RenameRegistry.model_validate(data).rename_project
            if not (result and (registry_project := result.project)):
                raise ValueError(failed_msg)

            if result.inserted:
                # This is not suppose trigger unless the user has messed with the `_saved_name` variable
                wandb.termlog(f"Created new registry {self.name!r} on save")

            self._update_attributes(registry_project)

    def _no_updating_registry_types(self) -> bool:
        # artifact types draft means user assigned types to add that are not yet saved
        return len(self.artifact_types.draft) > 0 and self.allow_all_artifact_types
