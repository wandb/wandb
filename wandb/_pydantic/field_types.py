"""Reusable field types and annotations for pydantic fields."""

from __future__ import annotations

from typing import Annotated, TypeAlias, TypeVar

from pydantic import Field, StrictStr

T = TypeVar("T")

Typename: TypeAlias = Annotated[T, Field(alias="__typename")]
"""Annotates GraphQL `__typename` fields."""


GQLId: TypeAlias = Annotated[StrictStr, Field()]
"""Annotates base64-encoded global ID (e.g. `Artifact:123`) fields."""
