"""Defined scopes."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import Field
from pydantic._internal import _repr
from typing_extensions import Annotated

from wandb.sdk.automations._base import Base
from wandb.sdk.automations._generated.enums import TriggerScopeType
from wandb.sdk.automations._typing import Base64Id, Typename


class BaseScope(Base):
    """Base class for automation scopes."""

    scope_type: ClassVar[TriggerScopeType]

    def __repr_args__(self) -> _repr.ReprArgs:
        if hasattr(self, "name"):
            yield "name", self.name


class ArtifactCollection(BaseScope):
    scope_type = TriggerScopeType.ARTIFACT_COLLECTION

    typename__: Typename[
        Literal["ArtifactSequence", "ArtifactPortfolio", "ArtifactCollection"]
    ] = "ArtifactCollection"
    id: Base64Id
    name: str | None = None


class Project(BaseScope):
    scope_type = TriggerScopeType.PROJECT

    typename__: Typename[Literal["Project"]] = "Project"
    id: Base64Id
    name: str | None = None


# AnyScope = ArtifactCollectionScope | ProjectScope
AnyScope = Annotated[
    ArtifactCollection | Project,
    Field(discriminator="typename__"),
]
