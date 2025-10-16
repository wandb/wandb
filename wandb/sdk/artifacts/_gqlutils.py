from __future__ import annotations

from functools import lru_cache

from wandb_gql import Client, gql

from wandb.proto.wandb_internal_pb2 import ServerFeature
from wandb.sdk.internal._generated import SERVER_FEATURES_QUERY_GQL, ServerFeaturesQuery

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
