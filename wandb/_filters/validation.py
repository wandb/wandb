"""Reusable validators for MongoDB-style filter dicts."""

from __future__ import annotations

from collections.abc import Callable, Collection
from dataclasses import dataclass, field
from typing import Any

from pydantic import GetCoreSchemaHandler, ValidationInfo
from pydantic_core import CoreSchema
from pydantic_core.core_schema import with_info_after_validator_function

from wandb._strutils import repr_join

from .filterutils import FilterFieldTransformer


@dataclass(frozen=True, slots=True)
class FilterValidator:
    """Pydantic metadata that validates and normalizes filter field names."""

    valid: Collection[str] | None = None
    """Allowed names, or aliases mapped to canonical serialized names."""

    resolve: Callable[[ValidationInfo], dict[str, str]] | None = field(
        default=None,
        kw_only=True,
        repr=False,
    )
    """Resolve an alias policy from Pydantic validation context."""

    _aliases: tuple[tuple[str, str], ...] = field(
        init=False,
        default=(),
        repr=False,
    )

    def __post_init__(self) -> None:
        if self.valid is not None and self.resolve is not None:
            raise ValueError("Specify either valid or resolve, not both.")

        # Empty collections are treated as None (no restrictions on valid names)
        if isinstance(valid := self.valid, dict):
            object.__setattr__(self, "_aliases", tuple(sorted(valid.items())))
        valid = frozenset(valid) if valid else None
        object.__setattr__(self, "valid", valid)

    def __get_pydantic_core_schema__(
        self, source_type: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        return with_info_after_validator_function(self.validate, handler(source_type))

    def validate(self, raw: dict[str, Any], info: ValidationInfo) -> dict[str, Any]:
        allowed: Collection[str] | None
        if self.resolve is not None:
            aliases = self.resolve(info)
            allowed = frozenset(aliases) if aliases else None
        else:
            aliases = dict(self._aliases)
            allowed = self.valid

        def validate_and_map(field: str, operand: Any) -> tuple[str, Any]:
            root, separator, suffix = field.partition(".")
            if allowed and root not in allowed:
                msg = f"Invalid filter field {root!r}, must be one of: {repr_join(sorted(allowed))}"
                raise ValueError(msg)

            mapped_root = aliases.get(root, root)
            return f"{mapped_root}{separator}{suffix}", operand

        return FilterFieldTransformer(validate_and_map).transform(raw)
