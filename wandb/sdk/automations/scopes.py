"""Scopes in which a W&B Automation can be triggered."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel

from wandb.apis import public

from ._base import Base, Base64Id, Typename
from ._generated.enums import TriggerScopeType

# NOTE: Enum is aliased to a shorter name for readability,
# in a public module for easier access
ScopeType = TriggerScopeType
"""The type of scope that triggers an automation."""


def get_scope(obj: Any) -> ScopeType:
    """Discriminator callable to get the scope type from an object."""
    from ._utils import SCOPE_TYPE_MAP

    if isinstance(obj, public.ArtifactCollection):
        return ScopeType.ARTIFACT_COLLECTION
    if isinstance(obj, public.Project):
        return ScopeType.PROJECT
    if isinstance(obj, Mapping):
        return SCOPE_TYPE_MAP[obj.get("typename__") or obj.get("__typename")]
    if isinstance(obj, BaseModel):
        return SCOPE_TYPE_MAP[obj.typename__]
    raise ValueError(f"Cannot get scope type from {type(obj).__qualname__!r}")


class ArtifactCollectionScope(Base):
    """The ID and name of the artifact collection scope of an automation."""

    typename__: Typename[
        Literal["ArtifactSequence", "ArtifactPortfolio", "ArtifactCollection"]
    ] = "ArtifactCollection"
    id: Base64Id
    name: str | None = None


class ProjectScope(Base):
    """The ID and name of the project scope of an automation."""

    typename__: Typename[Literal["Project"]] = "Project"
    id: Base64Id
    name: str | None = None
