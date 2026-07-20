"""Tests for the shared model factory helpers.

These cover only behavior this repo defines. Value generation itself
(filling fields, seeding, nested builds) is polyfactory's documented,
upstream-tested behavior and is exercised by the tests that use these
factories.
"""

from __future__ import annotations

import pytest
from wandb.sdk.artifacts._generated import ArtifactFragment

from tests.factories import build


def test_build_produces_valid_instance():
    artifact = build(ArtifactFragment, version_index=3)

    assert isinstance(artifact, ArtifactFragment)
    assert artifact.version_index == 3


def test_build_rejects_unknown_override():
    # Plain instantiation would silently ignore an unknown kwarg, letting
    # overrides go stale when a model changes shape. build() raises instead.
    with pytest.raises(TypeError, match="has no field"):
        build(ArtifactFragment, not_a_real_field="oops")
