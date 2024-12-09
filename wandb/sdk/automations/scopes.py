"""Defined scopes."""

from __future__ import annotations

from typing import Literal

from pydantic._internal import _repr

from ._base import Base, Base64Id, Typename


class _BaseScope(Base):
    """Base class for automation scopes."""

    def __repr_args__(self) -> _repr.ReprArgs:
        if name := getattr(self, "name", None):
            yield "name", name


class ArtifactCollection(_BaseScope):
    typename__: Typename[
        Literal["ArtifactSequence", "ArtifactPortfolio", "ArtifactCollection"]
    ] = "ArtifactCollection"
    id: Base64Id
    name: str | None = None


class Project(_BaseScope):
    typename__: Typename[Literal["Project"]] = "Project"
    id: Base64Id
    name: str | None = None
