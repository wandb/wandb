from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

from wandb_gql import gql

from wandb._iterutils import one
from wandb.proto.wandb_internal_pb2 import ServerFeature
from wandb.sdk.internal._generated import SERVER_FEATURES_QUERY_GQL, ServerFeaturesQuery

if TYPE_CHECKING:
    from wandb.apis.public import RetryingClient
    from wandb.sdk.artifacts._generated import TypeInfoFragment
    from wandb.sdk.artifacts._generated.fetch_org_info_from_entity import (
        FetchOrgInfoFromEntityEntity,
    )


@lru_cache(maxsize=16)
def type_info(client: RetryingClient, typename: str) -> TypeInfoFragment | None:
    """Returns the type info for a given GraphQL type."""
    from ._generated import TYPE_INFO_GQL, TypeInfo

    data = client.execute(gql(TYPE_INFO_GQL), variable_values={"name": typename})
    return TypeInfo.model_validate(data).type


@lru_cache(maxsize=16)
def org_info_from_entity(
    client: RetryingClient, entity: str
) -> FetchOrgInfoFromEntityEntity | None:
    """Returns the organization info for a given entity."""
    from ._generated import FETCH_ORG_INFO_FROM_ENTITY_GQL, FetchOrgInfoFromEntity

    gql_op = gql(FETCH_ORG_INFO_FROM_ENTITY_GQL)
    data = client.execute(gql_op, variable_values={"entity": entity})
    return FetchOrgInfoFromEntity.model_validate(data).entity


@lru_cache(maxsize=16)
def server_features(client: RetryingClient) -> dict[str, bool]:
    """Returns a mapping of `{server_feature_name (str) -> is_enabled (bool)}`.

    Results are cached per client instance.
    """
    try:
        response = client.execute(gql(SERVER_FEATURES_QUERY_GQL))
    except Exception as e:
        # Unfortunately we currently have to match on the text of the error message,
        # as the `gql` client raises `Exception` rather than a more specific error.
        if 'Cannot query field "features" on type "ServerInfo".' in str(e):
            return {}
        raise

    result = ServerFeaturesQuery.model_validate(response)
    if (server_info := result.server_info) and (features := server_info.features):
        return {feat.name: feat.is_enabled for feat in features if feat}
    return {}


def server_supports(client: RetryingClient, feature: str | int) -> bool:
    """Return whether the current server supports the given feature.

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
    return server_features(client).get(name) or False


def allowed_fields(client: RetryingClient, typename: str) -> set[str]:
    """Returns the allowed field names for a given GraphQL type."""
    typ = type_info(client, typename)
    return {f.name for f in typ.fields} if (typ and typ.fields) else set()


@dataclass(frozen=True)
class OrgInfo:
    org_name: str
    entity_name: str

    def __contains__(self, other: str) -> bool:
        return other in {self.org_name, self.entity_name}


def resolve_org_entity_name(
    client: RetryingClient,
    non_org_entity: str | None,
    org_or_entity: str | None = None,
) -> str:
    # Resolve the portfolio's org entity name.
    #
    # The `org_or_org_entity` parameter may be empty, an org display name, or an
    # org entity name.
    #
    # If the server cannot fetch the portfolio's org name, return the provided
    # value or raise an error if it is empty. Otherwise, return the fetched
    # value after validating that the given organization, if provided, matches
    # either the display or entity name.
    if not non_org_entity:
        raise ValueError("Entity name is required to resolve org entity name.")

    # Fetch candidate orgs to verify or identify the correct orgEntity name.
    entity = org_info_from_entity(client, non_org_entity)

    # Parse possible organization(s) from the response...
    # ----------------------------------------------------------------------------
    # If a team entity was provided, a single organization should exist under
    # the team/org entity type.
    if entity and (org := entity.organization) and (org_entity := org.org_entity):
        # Ensure the provided name, if given, matches the org or org entity name before
        # returning the org entity.
        org_info = OrgInfo(org_name=org.name, entity_name=org_entity.name)
        if (not org_or_entity) or (org_or_entity in org_info):
            return org_entity.name

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
                return next(
                    info.entity_name for info in org_infos if (org_or_entity in info)
                )

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
                (org.entity_name for org in org_infos),
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
