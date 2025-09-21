from __future__ import annotations

from functools import lru_cache

from wandb_gql import Client, gql

from ._generated import TYPE_INFO_GQL, TypeInfo

OMITTABLE_ARTIFACT_FIELDS = frozenset(
    {
        "ttlDurationSeconds",
        "ttlIsInherited",
        "aliases",
        "tags",
        "historyStep",
    }
)


@lru_cache(maxsize=128)
def allowed_fields(client: Client, typename: str) -> set[str]:
    """Returns the allowed field names for a given GraphQL type."""
    data = client.execute(gql(TYPE_INFO_GQL), variable_values={"name": typename})
    result = TypeInfo.model_validate(data)

    if (typ := result.type) and (fields := typ.fields):
        return {f.name for f in fields}
    return set()


@lru_cache(maxsize=16)
def omit_artifact_fields(client: Client) -> set[str]:
    """Return names of Artifact fields to remove from GraphQL requests (for server compatibility)."""
    return set(OMITTABLE_ARTIFACT_FIELDS) - allowed_fields(client, "Artifact")
