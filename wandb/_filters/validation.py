"""Reusable validators for MongoDB-style filter dicts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import GetCoreSchemaHandler
from pydantic_core import CoreSchema
from pydantic_core.core_schema import no_info_after_validator_function

from .filterutils import transform_fields


@dataclass(frozen=True, slots=True)
class FilterValidator:
    """Pydantic metadata that validates and normalizes filter field names."""

    valid: frozenset[str] | None = None
    """Allowed names, or aliases mapped to canonical serialized names."""

    aliases: tuple[tuple[str, str], ...] = field(init=False, default=())
    """Immutable accepted-to-canonical aliases derived from ``valid``."""

    def __post_init__(self) -> None:
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
        return no_info_after_validator_function(self.validate, handler(source_type))

    def validate(self, raw: dict[str, Any]) -> dict[str, Any]:
        return transform_fields(raw, aliases=dict(self.aliases) or None)
