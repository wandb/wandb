"""Reusable validators for MongoDB-style filter dicts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import GetCoreSchemaHandler
from pydantic_core import CoreSchema
from pydantic_core.core_schema import no_info_after_validator_function

from wandb._strutils import repr_join

from .filterutils import iter_fields, parse_filter


@dataclass(frozen=True, slots=True)
class FilterValidator:
    """Pydantic metadata that validates a MongoDB-style filter dict."""

    valid: frozenset[str] | None = None
    """The allowed field names. If None, all fields are allowed."""

    def __post_init__(self) -> None:
        # Empty collections are treated as None (no restrictions on valid names)
        valid = frozenset(valid) if (valid := self.valid) else None
        object.__setattr__(self, "valid", valid)

    def __get_pydantic_core_schema__(
        self, source_type: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        return no_info_after_validator_function(self.validate, handler(source_type))

    def validate(self, raw: dict[str, Any]) -> dict[str, Any]:
        parsed = parse_filter(raw)

        if valid := self.valid:
            # Check only root keys for dotted paths, e.g. "metadata.foo" -> "metadata"
            names = set(s.split(".")[0] for s in iter_fields(parsed))
            if invalid := names.difference(valid):
                msg = f"Invalid filter field(s) {repr_join(sorted(invalid))}, must be one of: {repr_join(sorted(valid))}"
                raise ValueError(msg)

        return raw  # Preserve the original dict so long as it's valid
