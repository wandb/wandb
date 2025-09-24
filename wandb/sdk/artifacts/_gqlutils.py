from __future__ import annotations

from wandb.sdk.internal.internal_api import Api as InternalApi

OMITTABLE_ARTIFACT_FIELDS = frozenset(
    {
        "ttlDurationSeconds",
        "ttlIsInherited",
        "aliases",
        "tags",
        "historyStep",
    }
)


def omit_artifact_fields(api: InternalApi | None = None) -> set[str]:
    """Return names of Artifact fields to remove from GraphQL requests (for server compatibility)."""
    allowed_fields = (api or InternalApi()).server_artifact_introspection()
    return set(OMITTABLE_ARTIFACT_FIELDS) - set(allowed_fields)
