from __future__ import annotations

from contextlib import suppress
from functools import lru_cache
from typing import NamedTuple, Sequence

from wandb_gql import Client, gql

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


def allowed_fields(client: Client, typename: str) -> set[str]:
    """Returns the allowed field names for a given GraphQL type."""
    typ = type_info(client, typename)
    return {f.name for f in typ.fields} if (typ and typ.fields) else set()


def omit_artifact_fields(client: Client) -> set[str]:
    """Return names of Artifact fields to remove from GraphQL requests (for server compatibility)."""
    return set(OMITTABLE_ARTIFACT_FIELDS) - allowed_fields(client, "Artifact")


class _OrgNames(NamedTuple):
    entity_name: str
    display_name: str

    def matches(self, org: str) -> bool:
        return org in {self.entity_name, self.display_name}


def match_org_to_fetched_org_entities(
    organization: str, all_org_names: Sequence[_OrgNames]
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
            names.entity_name for names in all_org_names if names.matches(organization)
        )

    # for org_names in orgs:
    #     if org_names.matches(organization):
    #         return org_names.entity_name

    if len(all_org_names) == 1:
        raise ValueError(
            f"Expecting the organization name or entity name to match {all_org_names[0].display_name!r} "
            f"and cannot be linked/fetched with {organization!r}. "
            "Please update the target path with the correct organization name."
        )

    raise ValueError(
        "Personal entity belongs to multiple organizations "
        f"and cannot be linked/fetched with {organization!r}. "
        "Please update the target path with the correct organization name "
        "or use a team entity in the entity settings."
    )


def _resolve_org_entity_name(
    client: Client, entity: str, organization: str = ""
) -> str:
    # resolveOrgEntityName fetches the portfolio's org entity's name.
    #
    # The organization parameter may be empty, an org's display name, or an org entity name.
    #
    # If the server doesn't support fetching the org name of a portfolio, then this returns
    # the organization parameter, or an error if it is empty. Otherwise, this returns the
    # fetched value after validating that the given organization, if not empty, matches
    # either the org's display or entity name.

    if not entity:
        raise ValueError("Entity name is required to resolve org entity name.")

    can_shorthand_org_entity = "orgEntity" in allowed_fields(client, "Organization")

    if not organization and not can_shorthand_org_entity:
        raise ValueError(
            "Fetching Registry artifacts without inputting an organization "
            "is unavailable for your server version. "
            "Please upgrade your server to 0.50.0 or later."
        )
    if not can_shorthand_org_entity:
        # Server doesn't support fetching org entity to validate,
        # assume org entity is correctly inputted
        return organization

    all_org_names = fetch_org_and_org_entity_names(entity)
    if organization:
        return match_org_to_fetched_org_entities(organization, all_org_names)

    # If no input organization provided, error if entity belongs to multiple orgs because we
    # cannot determine which one to use.
    if len(all_org_names) > 1:
        raise ValueError(
            f"Personal entity {entity!r} belongs to multiple organizations "
            "and cannot be used without specifying the organization name. "
            "Please specify the organization in the Registry path or use a team entity in the entity settings."
        )
    return all_org_names[0].entity_name


def fetch_org_and_org_entity_names(client: Client, entity_name: str) -> list[_OrgNames]:
    """Fetches organization entity names and display names for a given entity.

    Args:
        entity_name: Entity name to lookup. Can be either a personal or team entity.

    Returns:
        List[_OrgNames]: List of _OrgNames tuples. (_OrgNames(entity_name, display_name))

    Raises:
        ValueError: If entity is not found, has no organizations, or other validation errors.
    """
    gql_op = gql(FETCH_ORG_ENTITY_FROM_ENTITY_GQL)
    data = client.execute(gql_op, variable_values={"entityName": entity_name})
    entity = FetchOrgEntityFromEntity.model_validate(data).entity

    # Parse organization from response
    if entity and (org := entity.organization):
        # Check for organization under team/org entity type
        if org.name and org.org_entity and org.org_entity.name:
            return [_OrgNames(entity_name=org.org_entity.name, display_name=org.name)]

    elif entity and (user := entity.user):
        # Check for organization under personal entity type, where a user can belong to multiple orgs
        if parsed_names := [
            _OrgNames(entity_name=org.org_entity.name, display_name=org.name)
            for org in user.organizations
            if org.name and org.org_entity and org.org_entity.name
        ]:
            return parsed_names

        raise ValueError(
            f"Unable to resolve an organization associated with personal entity: {entity_name!r}. "
            "This could be because its a personal entity that doesn't belong to any organizations. "
            "Please specify the organization in the Registry path or use a team entity in the entity settings."
        )

    raise ValueError(f"Unable to find an organization under entity {entity_name!r}.")
