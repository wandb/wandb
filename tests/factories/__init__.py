"""Factories that generate valid instances of wandb's pydantic models for tests.

Built on polyfactory. Use these when a test needs a realistic, schema valid
object but only cares about a few of its fields. Pass the fields the test
reads or parses as overrides and let the factory fill in the rest.

Example:
    from tests.factories import build_dump
    from wandb.sdk.artifacts._generated import ArtifactFragment

    payload = build_dump(ArtifactFragment, version_index=0, state="COMMITTED")

This complements hypothesis rather than replacing it. Hypothesis remains the
tool for property based tests (invalid inputs, adversarial values, shrinking).
These factories produce a single valid instance per call.
"""

from __future__ import annotations

from functools import cache
from typing import Any, TypeVar

from polyfactory.factories.pydantic_factory import ModelFactory
from wandb._pydantic import GQLBase

_ModelT = TypeVar("_ModelT", bound=GQLBase)


class GQLFactory(ModelFactory[GQLBase]):
    """Shared configuration for factories of GQLBase models.

    Deliberately not marked with __is_base_factory__, which would register
    this class in polyfactory's global registry and change behavior for any
    other polyfactory usage in the same process.
    """

    __allow_none_optionals__ = False  # Always fill Optional fields.
    __use_defaults__ = True  # Let model defaults win, e.g. typename__ literals.


@cache
def factory_for(model: type[_ModelT]) -> type[ModelFactory[_ModelT]]:
    """Return a factory for the given model, creating one if needed."""
    return GQLFactory.create_factory(model)


def build(model: type[_ModelT], **overrides: Any) -> _ModelT:
    """Build a valid model instance, generating any unspecified field values.

    Overrides use field names, not aliases. Plain model instantiation
    silently ignores unknown keyword arguments, so overrides can go stale
    without anyone noticing when a model changes shape. This raises
    TypeError instead. The check covers only the top level. Values nested
    inside dict overrides get pydantic's usual handling.
    """
    if unknown := set(overrides) - set(model.model_fields):
        raise TypeError(
            f"{model.__name__} has no field(s) {sorted(unknown)}. "
            f"Valid fields: {sorted(model.model_fields)}"
        )
    return factory_for(model).build(**overrides)


def build_dump(model: type[GQLBase], **overrides: Any) -> dict[str, Any]:
    """Like build(), but returns the dumped dict instead of the instance.

    GQLBase models dump by alias, so for generated GraphQL types this is a
    camelCase payload shaped like a server response.
    """
    return build(model, **overrides).model_dump()
