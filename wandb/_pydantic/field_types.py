"""Reusable field types and annotations for pydantic fields."""

from __future__ import annotations

from typing import Annotated, TypeVar

from pydantic import Field, StrictStr

T = TypeVar("T")

# HACK: Pydantic no longer seems to like it when you define a type alias
# at the module level with `Annotated[...]`.
# The commented TypeAliases are a hack to unblock CI for now.

# Typename = Annotated[T, Field(repr=False, frozen=True, alias="__typename")]
Typename = Annotated[T, Field(alias="__typename")]
"""Annotates GraphQL `__typename` fields."""

# GQLId = Annotated[StrictStr, Field(repr=False, frozen=True)]
GQLId = StrictStr
