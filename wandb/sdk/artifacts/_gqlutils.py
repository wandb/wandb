from __future__ import annotations

from contextlib import suppress
from functools import lru_cache
from typing import Sequence

from wandb_gql import Client, gql

from wandb._iterutils import one
from wandb.sdk.artifacts._generated.fragments import OrgWithEntityFragment

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


# @pydantic_dataclass(frozen=True)
# class OrgAliases:
#     org_entity_name: str
#     org_name: str


def match_org_to_fetched_org_entities(
    maybe_org_name: str, possible_orgs: Sequence[OrgWithEntityFragment]
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
            org_entity.name
            for org in possible_orgs
            if (org_entity := org.org_entity)
            and maybe_org_name in {org.org_name, org_entity.name}
        )

    if len(possible_orgs) == 1:
        raise ValueError(
            f"Expecting the organization name or entity name to match {possible_orgs[0].org_name!r} "
            f"and cannot be linked/fetched with {maybe_org_name!r}. "
            "Please update the target path with the correct organization name."
        )

    raise ValueError(
        "Personal entity belongs to multiple organizations "
        f"and cannot be linked/fetched with {maybe_org_name!r}. "
        "Please update the target path with the correct organization name "
        "or use a team entity in the entity settings."
    )


def resolve_org_entity_name(
    client: Client, non_org_entity: str, maybe_org_name: str | None = None
) -> str:
    # resolveOrgEntityName fetches the portfolio's org entity's name.
    #
    # The maybe_org_name parameter may be empty, an org's display name, or an org entity name.
    #
    # If the server doesn't support fetching the org name of a portfolio, then this returns
    # the maybe_org_name parameter, or an error if it is empty. Otherwise, this returns the
    # fetched value after validating that the given organization, if not empty, matches
    # either the org's display or entity name.

    can_shorthand_org_entity = "orgEntity" in allowed_fields(client, "Organization")

    if not can_shorthand_org_entity:
        if not maybe_org_name:
            raise ValueError(
                "Fetching Registry artifacts without inputting an organization "
                "is unavailable for your server version. "
                "Please upgrade your server to 0.50.0 or later."
            )

        # Server doesn't support fetching org entity to validate.
        # Assume org entity is correctly provided.
        return maybe_org_name

    possible_orgs = fetch_org_with_entity_fragments(client, non_org_entity)
    if maybe_org_name:
        return match_org_to_fetched_org_entities(maybe_org_name, possible_orgs)

    # If no input organization provided, error if entity belongs to:
    # - multiple orgs, because we cannot determine which one to use.
    # - no orgs, because there's nothing to use.
    only_org = one(
        possible_orgs,
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

    return only_org.org_entity_name


def fetch_org_with_entity_fragments(
    client: Client, non_org_entity: str
) -> list[OrgWithEntityFragment]:
    """Fetches organization entity names and display names for a given entity.

    Args:
        entity_name: Entity name to lookup. Can be either a personal or team entity.

    Returns:
        List[_OrgNames]: List of _OrgNames tuples. (_OrgNames(entity_name, display_name))

    Raises:
        ValueError: If entity is not found, has no organizations, or other validation errors.
    """
    gql_op = gql(FETCH_ORG_ENTITY_FROM_ENTITY_GQL)
    data = client.execute(gql_op, variable_values={"entityName": non_org_entity})
    entity = FetchOrgEntityFromEntity.model_validate(data).entity

    # Parse possible organization(s) from the response

    # If a team entity was provided, there should be a single organization under team/org entity type
    if entity and (org := entity.organization) and org.org_entity:
        return [org]
        # return [OrgAliases(org_entity_name=org_entity.name, org_name=org.name)]

    # If a personal entity was provided, there may be multiple organizations that the user belongs to
    if entity and (user := entity.user):
        return [
            # OrgAliases(org_entity_name=org_entity.name, org_name=org.name)
            org
            for org in user.organizations
            if org.org_entity
        ]

    raise ValueError(f"Unable to find an organization under entity {non_org_entity!r}.")
