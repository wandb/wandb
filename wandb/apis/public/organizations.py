"""W&B Public API for reading organizations."""

from __future__ import annotations

from dataclasses import KW_ONLY, InitVar
from typing import Literal

from pydantic import ConfigDict
from pydantic.alias_generators import to_camel
from pydantic.dataclasses import dataclass as pydantic_dataclass

from wandb._pydantic import GQLId, GQLResult, Typename

from .service_api import ServiceApi


class _OrgEntity(GQLResult):
    """The internal entity associated with a W&B organization."""

    typename__: Typename[Literal["Entity"]] = "Entity"

    id: GQLId
    name: str
    entity_type: Literal["organization"] = "organization"


@pydantic_dataclass(
    frozen=True,
    config=ConfigDict(alias_generator=to_camel, arbitrary_types_allowed=True),
)
class Organization:
    """A read-only representation of a W&B organization.

    Users should never need to instantiate this class directly. Use
    `wandb.Api().organization()` to fetch an existing organization.
    """

    # init-only arg, assigned as a private attribute on instantiation. Meant to
    # ensure a consistent signature/shape as other existing types (e.g. Project/Team/etc).
    service_api: InitVar[ServiceApi]

    _: KW_ONLY

    id: GQLId
    name: str
    org_entity: _OrgEntity

    def __post_init__(self, service_api: ServiceApi) -> None:
        # Slight hack, but needed to assign self._service_api while keeping frozen=True.
        object.__setattr__(self, "_service_api", service_api)
