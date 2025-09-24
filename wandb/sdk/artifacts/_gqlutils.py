from __future__ import annotations

from functools import lru_cache

from wandb_gql import Client, gql

from ._generated import TYPE_INFO_GQL, TypeInfo, TypeInfoFragment

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
