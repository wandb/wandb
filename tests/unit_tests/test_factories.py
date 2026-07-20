"""Tests for the shared model factories in tests/factories."""

from __future__ import annotations

import pytest
from wandb.automations import Automation
from wandb.sdk.artifacts._generated import ArtifactFragment

from tests.factories import GQLFactory, build, build_dump


def test_build_fills_unspecified_fields():
    artifact = build(ArtifactFragment, version_index=3)

    assert isinstance(artifact, ArtifactFragment)
    assert artifact.version_index == 3
    # Fields the caller didn't specify get generated values, including
    # Optional ones (the factory always fills Optional fields).
    assert isinstance(artifact.digest, str)
    assert artifact.artifact_sequence is not None


def test_build_accepts_nested_overrides():
    artifact = build(
        ArtifactFragment,
        artifact_sequence={
            "name": "seq-name",
            "project": {"name": "proj", "entity": {"name": "test-entity"}},
        },
    )

    assert artifact.artifact_sequence.name == "seq-name"
    assert artifact.artifact_sequence.project.entity.name == "test-entity"


def test_build_rejects_unknown_override():
    # Plain instantiation would silently ignore an unknown kwarg, letting
    # overrides go stale when a model changes shape. build() raises instead.
    with pytest.raises(TypeError, match="has no field"):
        build(ArtifactFragment, not_a_real_field="oops")


def test_build_dump_returns_gql_shaped_payload():
    payload = build_dump(ArtifactFragment, version_index=1)

    # GQLBase models dump by alias, so keys are camelCase GraphQL names.
    assert payload["versionIndex"] == 1
    assert payload["__typename"] == "Artifact"

    # The payload round trips through validation.
    assert ArtifactFragment.model_validate(payload).version_index == 1


def test_builds_are_deterministic_per_seed():
    GQLFactory.seed_random(1234)
    first = build_dump(ArtifactFragment)

    GQLFactory.seed_random(1234)
    second = build_dump(ArtifactFragment)

    assert first == second


def test_build_handles_unions_and_json_fields():
    # Automation exercises the harder model features in one build: scope,
    # event, and action are unions discriminated on typename__, and the
    # event filter is a JSON encoded string field. Dumping and revalidating
    # checks that every generated value serializes back into a valid payload.
    automation = build(Automation, name="my-automation")

    assert automation.name == "my-automation"
    assert automation.scope is not None
    assert automation.action is not None

    round_tripped = Automation.model_validate(automation.model_dump())
    assert round_tripped.name == "my-automation"
