"""Factories that generate valid instances of wandb's pydantic models for tests.

Built on polyfactory. Use these when a test needs a realistic, schema valid
object but only cares about a few of its fields. Pass those fields as
overrides (by field name, not alias) and the factory fills in the rest.

Tests should normally use the ``gql_factory`` fixture rather than importing
from this module, so that generated values are seeded deterministically:

    artifact = gql_factory(ArtifactFragment).build(version_index=0)
    payload = gql_factory(ArtifactFragment).build(version_index=0).model_dump()

This complements hypothesis rather than replacing it. Hypothesis remains the
tool for property based tests (invalid inputs, adversarial values, shrinking).
These factories produce a single valid instance per call.
"""

from __future__ import annotations

from functools import cache
from typing import TypeVar

from polyfactory.factories.pydantic_factory import ModelFactory
from wandb._pydantic import GQLBase

_ModelT = TypeVar("_ModelT", bound=GQLBase)


class GQLFactory(ModelFactory[GQLBase]):
    """Shared configuration for factories of GQLBase models.

    This deliberately does not set __is_base_factory__, which would append
    the class to polyfactory's process global factory registry and apply
    this configuration to every pydantic model built by any polyfactory
    factory in the process. Leaving it unset scopes the configuration to
    factories created through factory_for().
    """

    __allow_none_optionals__ = False  # Always fill Optional fields.
    __use_defaults__ = True  # Let model defaults win, e.g. typename__ literals.


@cache
def factory_for(model: type[_ModelT]) -> type[ModelFactory[_ModelT]]:
    """Return a factory for the given model, creating one if needed."""
    return GQLFactory.create_factory(model)
