from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

from wandb._iterutils import one
from wandb.proto.wandb_internal_pb2 import ServerFeature
from wandb.sdk.internal._generated import SERVER_FEATURES_QUERY_GQL, ServerFeaturesQuery

if TYPE_CHECKING:
    from wandb.apis.public.service_api import ServiceApi
    from wandb.sdk.artifacts._generated.fetch_org_info_from_entity import (
        FetchOrgInfoFromEntityEntity,
    )


@lru_cache(maxsize=16)
def org_info_from_entity(
    service_api: ServiceApi, entity: str
) -> FetchOrgInfoFromEntityEntity | None:
    """Returns the organization info for a given entity."""
    from ._generated import FETCH_ORG_INFO_FROM_ENTITY_GQL, FetchOrgInfoFromEntity

    result = service_api.execute_graphql(
        FETCH_ORG_INFO_FROM_ENTITY_GQL,
        variables={"entity": entity},
        parse=FetchOrgInfoFromEntity.model_validate_json,
    )
    return result.entity


@lru_cache(maxsize=16)
def _server_features(service_api: ServiceApi) -> dict[str, bool]:
    """Returns a mapping of `{server_feature_name (str) -> is_enabled (bool)}`.

    Results are cached per service API instance.
    """
    try:
        result = service_api.execute_graphql(
            SERVER_FEATURES_QUERY_GQL,
            parse=ServerFeaturesQuery.model_validate_json,
        )
    except Exception as e:
        # Unfortunately we currently have to match on the text of the error message,
        # as the `gql` client raises `Exception` rather than a more specific error.
        if 'Cannot query field "features" on type "ServerInfo".' in str(e):
            return {}
        raise

    if (server_info := result.server_info) and (features := server_info.features):
        return {feat.name: feat.is_enabled for feat in features if feat}
    return {}


def server_supports(service_api: ServiceApi, feature: str | int) -> bool:
    """Return whether the current server supports the given feature.

    NOTE: This is deprecated. Please use `ServiceApi.feature_enabled()` when
    possible, like in all public API code.

    Good to use for features that have a fallback mechanism for older servers.
    """
    # If we're given the protobuf enum value, convert to a string name.
    # NOTE: We deliberately use names (str) instead of enum values (int)
    # as the keys here, since:
    # - the server identifies features by their name, rather than (client-side) enum value
    # - the defined list of client-side flags may be behind the server-side list of flags
    try:
        name = ServerFeature.Name(feature) if isinstance(feature, int) else feature
    except ValueError:
        return False  # Invalid int-like value, assume unsupported
    return _server_features(service_api).get(name) or False


@dataclass(frozen=True)
class OrgInfo:
    org_name: str
    entity_name: str

    def __contains__(self, other: str) -> bool:
        return other in {self.org_name, self.entity_name}


def _resolve_org_info(
    service_api: ServiceApi,
    non_org_entity: str | None,
    org_or_entity: str | None = None,
) -> OrgInfo:
    # Resolve an entity's organization to an `OrgInfo` (carrying both the org's
    # display name and its org-entity name).
    #
    # The `org_or_entity` parameter may be empty, an org display name, or an org
    # entity name. When provided, it's validated against the entity's org(s).
    if not non_org_entity:
        raise ValueError("Entity name is required to resolve org entity name.")

    # Fetch candidate orgs to verify or identify the correct organization.
    entity = org_info_from_entity(service_api, non_org_entity)

    # Parse possible organization(s) from the response...
    # ----------------------------------------------------------------------------
    # If a team entity was provided, a single organization should exist under
    # the team/org entity type.
    if entity and (org := entity.organization) and (org_entity := org.org_entity):
        # Ensure the provided name, if given, matches the org or org entity name before
        # returning the org.
        org_info = OrgInfo(org_name=org.name, entity_name=org_entity.name)
        if (not org_or_entity) or (org_or_entity in org_info):
            return org_info

    # ----------------------------------------------------------------------------
    # If a personal entity was provided, the user may belong to multiple
    # organizations.
    if entity and (user := entity.user) and (orgs := user.organizations):
        org_infos = [
            OrgInfo(org_name=org.name, entity_name=org_entity.name)
            for org in orgs
            if (org_entity := org.org_entity)
        ]
        if org_or_entity:
            with suppress(StopIteration):
                return next(info for info in org_infos if (org_or_entity in info))

            if len(org_infos) == 1:
                raise ValueError(
                    f"Expecting the organization name or entity name to match {org_infos[0].org_name!r} "
                    f"and cannot be linked/fetched with {org_or_entity!r}. "
                    "Please update the target path with the correct organization name."
                )
            else:
                raise ValueError(
                    "Personal entity belongs to multiple organizations "
                    f"and cannot be linked/fetched with {org_or_entity!r}. "
                    "Please update the target path with the correct organization name "
                    "or use a team entity in the entity settings."
                )

        else:
            # If no input organization provided, error if entity belongs to:
            # - multiple orgs, because we cannot determine which one to use.
            # - no orgs, because there's nothing to use.
            return one(
                org_infos,
                too_short=ValueError(
                    f"Unable to resolve an organization associated with personal entity: {non_org_entity!r}. "
                    "This could be because its a personal entity that doesn't belong to any organizations. "
                    "Please specify the organization in the Registry path or use a team entity in the entity settings."
                ),
                too_long=ValueError(
                    f"Personal entity {non_org_entity!r} belongs to multiple organizations "
                    "and cannot be used without specifying the organization name. "
                    "Please specify the organization in the Registry path or use a team entity in the entity settings."
                ),
            )

    raise ValueError(f"Unable to find organization for entity {non_org_entity!r}.")


def resolve_org_entity_name(
    service_api: ServiceApi,
    non_org_entity: str | None,
    org_or_entity: str | None = None,
) -> str:
    """Resolve an entity's organization to its org **entity** name."""
    return _resolve_org_info(service_api, non_org_entity, org_or_entity).entity_name


def resolve_org_name(
    service_api: ServiceApi,
    non_org_entity: str | None,
    org_or_entity: str | None = None,
) -> str:
    """Resolve an entity's organization to its **display** name."""
    return _resolve_org_info(service_api, non_org_entity, org_or_entity).org_name


def is_project_read_only(
    service_api: ServiceApi, entity: str, project: str
) -> bool | None:
    """Return whether *project* is read-only for the caller, or None if invisible."""
    from wandb.apis._generated import IS_PROJECT_READ_ONLY_GQL, IsProjectReadOnly

    result = service_api.execute_graphql(
        IS_PROJECT_READ_ONLY_GQL,
        variables={"entity": entity, "project": project},
        parse=IsProjectReadOnly.model_validate_json,
    )
    if not (result and (proj := result.project)):
        return None
    return proj.read_only
