"""Shared base for factories that generate wandb pydantic models in tests.

Built on polyfactory. Concrete factories subclass GQLFactory, set __model__,
and are registered as explicitly named pytest fixtures in the conftest
nearest their users:

    from polyfactory.pytest_plugin import register_fixture

    from tests.factories import GQLFactory

    @register_fixture(name="artifact_fragment_factory")
    class ArtifactFragmentFactory(GQLFactory):
        __model__ = ArtifactFragment

A test then requests the fixture and states only the fields it cares about,
by field name rather than alias. The factory fills in the rest with schema
valid values:

    artifact = artifact_fragment_factory.build(version_index=0)

This complements hypothesis rather than replacing it. Hypothesis remains the
tool for property based tests (invalid inputs, adversarial values, shrinking).
These factories produce a single valid instance per call.
"""

from __future__ import annotations

from polyfactory.factories.pydantic_factory import ModelFactory
from wandb._pydantic import GQLBase


class GQLFactory(ModelFactory[GQLBase]):
    """Shared configuration for factories of GQLBase models.

    This deliberately does not set __is_base_factory__, which would append
    the class to polyfactory's process global factory registry and apply
    this configuration to every pydantic model built by any polyfactory
    factory in the process. Leaving it unset scopes the configuration to
    this class's subclasses.
    """

    # Always fill Optional fields. Generated values are seeded from the test's
    # node id, so if optionals could be None, the structure of generated data
    # would flip with incidental changes like renaming a test. Tests that care
    # about a None value set it explicitly when building.
    __allow_none_optionals__ = False
