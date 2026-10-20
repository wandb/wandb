"""Tests for Artifact._update()'s use of the artifactMembership payload field.

`updateArtifact` can return `artifactMembership` directly, letting
`Artifact._assign_attrs` resolve version/aliases from the single membership
instead of falling back to the artifact-wide `aliases` field (which fans out
across every collection the artifact belongs to). These tests cover both
sides of that branch: the ARTIFACT_MEMBERSHIP_ON_ARTIFACT_PAYLOAD feature
being enabled and disabled.
"""

from __future__ import annotations

from typing import Any

from wandb.apis.public.service_api import ServiceApi
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.artifacts._generated.fragments import ArtifactFragment
from wandb.sdk.artifacts._generated.update_artifact import (
    UpdateArtifact,
    UpdateArtifactResult,
)
from wandb.sdk.artifacts._validators import FullArtifactPath
from wandb.sdk.artifacts.artifact import Artifact
from wandb.sdk.wandb_settings import Settings

_PROJECT_DICT = {
    "id": "project-id",
    "internalId": "1",
    "name": "my-project",
    "entity": {"name": "my-entity"},
}
_COLLECTION_DICT = {
    "__typename": "ArtifactSequence",
    "name": "my-collection",
    "project": _PROJECT_DICT,
}


def _alias_dict(alias: str) -> dict[str, Any]:
    return {
        "id": f"alias-{alias}",
        "alias": alias,
        "artifactCollection": _COLLECTION_DICT,
    }


def _artifact_fragment_dict(
    *, artifact_id: str, version_index: int, aliases: list[str]
) -> dict[str, Any]:
    return {
        "id": artifact_id,
        "artifactSequence": {"name": "my-collection", "project": _PROJECT_DICT},
        "versionIndex": version_index,
        "artifactType": {"name": "dataset"},
        "description": None,
        "metadata": None,
        "ttlDurationSeconds": -1,
        "ttlIsInherited": True,
        "tags": [],
        "historyStep": None,
        "state": "COMMITTED",
        "size": 0,
        "digest": "abc123",
        "commitHash": None,
        "fileCount": 0,
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": None,
        "aliases": [_alias_dict(a) for a in aliases],
    }


def _membership_fragment_dict(
    *,
    membership_id: str,
    version_index: int,
    aliases: list[str],
    artifact: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": membership_id,
        "versionIndex": version_index,
        "createdAt": "2026-01-01T00:00:00Z",
        "aliases": [{"id": f"alias-{a}", "alias": a} for a in aliases],
        "artifactCollection": _COLLECTION_DICT,
        "artifact": artifact,
    }


def _make_logged_artifact(*, service_api: ServiceApi) -> Artifact:
    """Builds a committed Artifact the same way _from_attrs does internally,
    seeded with one non-version alias so the test can tell whether later
    reads come from the artifact or the membership.
    """
    path = FullArtifactPath(
        name="my-collection", project="my-project", prefix="my-entity"
    )
    src_art = ArtifactFragment.model_validate(
        _artifact_fragment_dict(
            artifact_id="artifact-id",
            version_index=0,
            aliases=["from-artifact"],
        )
    )
    return Artifact._from_attrs(path, src_art, service_api)


def test_update_uses_membership_when_feature_enabled():
    service_api = ServiceApi(Settings())
    service_api.feature_enabled = lambda feature, **kwargs: (
        feature == pb.ARTIFACT_MEMBERSHIP_ON_ARTIFACT_PAYLOAD
    )

    artifact = _make_logged_artifact(service_api=service_api)

    captured: dict[str, Any] = {}

    def fake_execute_graphql(query, *, variables=None, parse=None, omit_fields=None):
        captured["omit_fields"] = omit_fields
        return UpdateArtifact(
            result=UpdateArtifactResult.model_validate(
                {
                    "artifact": _artifact_fragment_dict(
                        artifact_id="artifact-id",
                        version_index=1,
                        aliases=["from-artifact"],
                    ),
                    "artifactMembership": _membership_fragment_dict(
                        membership_id="membership-id",
                        version_index=5,
                        aliases=["from-membership"],
                        artifact=_artifact_fragment_dict(
                            artifact_id="artifact-id",
                            version_index=1,
                            aliases=["from-artifact"],
                        ),
                    ),
                }
            )
        )

    service_api.execute_graphql = fake_execute_graphql

    artifact._update()

    assert "artifactMembership" not in captured["omit_fields"]
    # Resolved from the membership (versionIndex=5, alias "from-membership"),
    # not the bare artifact (versionIndex=1, alias "from-artifact").
    assert artifact.version == "v5"
    assert "from-membership" in artifact.aliases
    assert "from-artifact" not in artifact.aliases


def test_update_omits_membership_when_feature_disabled():
    service_api = ServiceApi(Settings())
    service_api.feature_enabled = lambda feature, **kwargs: False

    artifact = _make_logged_artifact(service_api=service_api)

    captured: dict[str, Any] = {}

    def fake_execute_graphql(query, *, variables=None, parse=None, omit_fields=None):
        captured["omit_fields"] = omit_fields
        return UpdateArtifact(
            result=UpdateArtifactResult.model_validate(
                {
                    "artifact": _artifact_fragment_dict(
                        artifact_id="artifact-id",
                        version_index=1,
                        aliases=["from-artifact"],
                    ),
                }
            )
        )

    service_api.execute_graphql = fake_execute_graphql

    artifact._update()

    assert "artifactMembership" in captured["omit_fields"]
    # Falls back to the bare artifact's own aliases/version, matching
    # pre-existing behavior against servers that don't support the field.
    assert artifact.version == "v1"
    assert "from-artifact" in artifact.aliases
