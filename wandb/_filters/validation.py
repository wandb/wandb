"""Reusable validators for MongoDB-style filter dicts."""

from __future__ import annotations

from collections.abc import Callable, Collection
from dataclasses import dataclass, field
from typing import Any

from pydantic import GetCoreSchemaHandler, ValidationInfo
from pydantic_core import CoreSchema
from pydantic_core.core_schema import with_info_after_validator_function

from .filterutils import transform_fields

AliasResolver = Callable[[ValidationInfo], dict[str, str]]


@dataclass(frozen=True, slots=True)
class FilterValidator:
    """Pydantic metadata that validates and normalizes filter field names."""

    valid: Collection[str] | None = None
    """Allowed names, or aliases mapped to canonical serialized names."""

    alias_resolver: AliasResolver | None = None
    """Resolve accepted-to-canonical aliases from Pydantic validation context."""

    aliases: tuple[tuple[str, str], ...] = field(init=False, default=())
    """Immutable accepted-to-canonical aliases derived from ``valid``."""

    def __post_init__(self) -> None:
        if self.valid and self.alias_resolver:
            raise ValueError("Specify either valid or alias_resolver, not both.")

        # Empty collections are treated as None (no restrictions on valid names)
        if isinstance(valid := self.valid, dict):
            aliases = tuple(sorted(valid.items()))
        else:
            aliases = tuple((name, name) for name in sorted(valid or ()))
        object.__setattr__(self, "aliases", aliases)

        valid = frozenset(valid) if valid else None
        object.__setattr__(self, "valid", valid)

    def __get_pydantic_core_schema__(
        self, source_type: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        return with_info_after_validator_function(self.validate, handler(source_type))

    def validate(self, raw: dict[str, Any], info: ValidationInfo) -> dict[str, Any]:
        aliases = (
            resolve(info) if (resolve := self.alias_resolver) else dict(self.aliases)
        )
        return transform_fields(raw, aliases=aliases or None)
