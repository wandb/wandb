from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from functools import lru_cache
from typing import Sequence

from wandb_gql import Client, gql

from wandb._iterutils import one
from wandb.errors import UnsupportedError
from wandb.proto.wandb_internal_pb2 import ServerFeature
from wandb.sdk.internal._generated import SERVER_FEATURES_QUERY_GQL, ServerFeaturesQuery

from ._generated import (
    FETCH_ORG_ENTITY_FROM_ENTITY_GQL,
    TYPE_INFO_GQL,
    FetchOrgEntityFromEntity,
    TypeInfo,
    TypeInfoFragment,
)

OMITTABLE_ARTIFACT_FIELDS = frozenset(
    {
        "ttlDurationSeconds",
        "ttlIsInherited",
        "aliases",
        "tags",
        "historyStep",
    }
)


@lru_cache(maxsize=16)
def type_info(client: Client, typename: str) -> TypeInfoFragment | None:
    """Returns the type info for a given GraphQL type."""
    data = client.execute(gql(TYPE_INFO_GQL), variable_values={"name": typename})
    return TypeInfo.model_validate(data).type


@lru_cache(maxsize=16)
def server_features(client: Client) -> dict[str, bool]:
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


def server_supports(client: Client, feature: str | int) -> bool:
    """Return whether the current server supports the given feature.

    Good to use for features that have a fallback mechanism for older servers.
    """
    # If we're given the protobuf enum value, convert to a string name.
    # NOTE: We deliberately use names (str) instead of enum values (int)
    # as the keys here, since:
    # - the server identifies features by their name, rather than (client-side) enum value
    # - the defined list of client-side flags may be behind the server-side list of flags
    feature_name = ServerFeature.Name(feature) if isinstance(feature, int) else feature
    return server_features(client).get(feature_name) or False


def supports_enable_tracking_var(client: Client) -> bool:
    """Returns True if the server supports the `enableTracking` variable for the `Project.artifact(...)` field."""
    typ = type_info(client, "Project")
    if (
        typ
        and typ.fields
        and (art_field := next((f for f in typ.fields if f.name == "artifact"), None))
    ):
        return any("enableTracking" == arg.name for arg in art_field.args)
    return False


def supports_org_entity_field(client: Client) -> bool:
    """Returns True if the server supports the `orgEntity` field for the `Organization` type."""
    return "orgEntity" in allowed_fields(client, "Organization")


def allowed_fields(client: Client, typename: str) -> set[str]:
    """Returns the allowed field names for a given GraphQL type."""
    typ = type_info(client, typename)
    return {f.name for f in typ.fields} if (typ and typ.fields) else set()


def omit_artifact_fields(client: Client) -> set[str]:
    """Return names of Artifact fields to remove from GraphQL requests (for server compatibility)."""
    return set(OMITTABLE_ARTIFACT_FIELDS) - allowed_fields(client, "Artifact")


@dataclass(frozen=True)
class OrgNames:
    display_name: str
    entity_name: str

    def __contains__(self, other: str) -> bool:
        return other in {self.display_name, self.entity_name}


def get_matching_org_entity_name(
    org_or_entity: str, all_org_names: Sequence[OrgNames]
) -> str:
    """Match the organization provided in the path with the org entity or org name of the input entity.

    Args:
        organization: The organization name to match
        orgs: List of tuples containing (org_entity_name, org_display_name)

    Returns:
        str: The matched org entity name

    Raises:
        ValueError: If no matching organization is found or if multiple orgs exist without a match
    """
    with suppress(StopIteration):
        return next(
            names.entity_name for names in all_org_names if org_or_entity in names
        )

    if len(all_org_names) == 1:
        raise ValueError(
            f"Expecting the organization name or entity name to match {all_org_names[0].display_name!r} "
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


def resolve_org_entity_name(
    client: Client,
    entity_name: str,
    org_or_entity: str | None = None,
) -> str:
    # resolveOrgEntityName fetches the portfolio's org entity's name.
    #
    # The maybe_org_name parameter may be empty, an org's display name, or an org entity name.
    #
    # If the server doesn't support fetching the org name of a portfolio, then this returns
    # the maybe_org_name parameter, or an error if it is empty. Otherwise, this returns the
    # fetched value after validating that the given organization, if not empty, matches
    # either the org's display or entity name.

    if supports_org_entity_field(client):
        all_org_names = fetch_org_infos(client, entity_name)
        if org_or_entity:
            return get_matching_org_entity_name(org_or_entity, all_org_names)

        # If no input organization provided, error if entity belongs to:
        # - multiple orgs, because we cannot determine which one to use.
        # - no orgs, because there's nothing to use.
        return one(
            (org.entity_name for org in all_org_names),
            too_short=ValueError(
                f"Unable to resolve an organization associated with personal entity: {entity_name!r}. "
                "This could be because its a personal entity that doesn't belong to any organizations. "
                "Please specify the organization in the Registry path or use a team entity in the entity settings."
            ),
            too_long=ValueError(
                f"Personal entity {entity_name!r} belongs to multiple organizations "
                "and cannot be used without specifying the organization name. "
                "Please specify the organization in the Registry path or use a team entity in the entity settings."
            ),
        )
    elif org_or_entity:
        # Server doesn't support fetching org entity to validate.
        # Assume org entity is correctly provided.
        return org_or_entity
    else:
        raise UnsupportedError(
            "Fetching Registry artifacts without inputting an organization "
            "is unavailable for your server version. "
            "Please upgrade your server to 0.50.0 or later."
        )


def fetch_org_infos(client: Client, entity_name: str) -> list[OrgNames]:
    """Fetches organization entity names and display names for a given entity.

    Args:
        entity_name: Entity name to lookup. Can be either a personal or team entity.

    Raises:
        ValueError: If entity is not found, has no organizations, or other validation errors.
    """
    gql_op = gql(FETCH_ORG_ENTITY_FROM_ENTITY_GQL)
    data = client.execute(gql_op, variable_values={"entity": entity_name})
    entity = FetchOrgEntityFromEntity.model_validate(data).entity

    # Parse possible organization(s) from the response
    if (
        (team_entity := entity)
        and (org := team_entity.organization)
        and (org_entity := org.org_entity)
    ):
        # If a team entity was provided, there should be a single organization under team/org entity type
        return [OrgNames(display_name=org.name, entity_name=org_entity.name)]

    if (user_entity := entity) and (user := user_entity.user) and user.organizations:
        # If a personal entity was provided, there may be multiple organizations that the user belongs to
        return [
            OrgNames(display_name=org.name, entity_name=org_entity.name)
            for org in user.organizations
            if (org_entity := org.org_entity)
        ]

    raise ValueError(f"Unable to find an organization under entity {entity_name!r}.")
