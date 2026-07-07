"""Reusable validators for MongoDB-style filter dicts."""

from __future__ import annotations

from collections.abc import Collection
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

    valid: Collection[str] | None = None
    """The allowed field names. If None, all fields are allowed."""

    def __post_init__(self) -> None:
        if valid := self.valid:
            object.__setattr__(self, "valid", frozenset(valid))

    def __get_pydantic_core_schema__(
        self, source_type: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        return no_info_after_validator_function(self.validate, handler(source_type))

    def validate(self, arg: dict[str, Any]) -> dict[str, Any]:
        if valid := self.valid:
            # For dotted paths, check only the top-level name.
            #   e.g. "metadata.foo" -> "metadata"
            seen = set(s.split(".")[0] for s in iter_fields(parse_filter(arg)))
            if invalid := seen.difference(valid):
                msg = f"Invalid filter field(s) {repr_join(sorted(invalid))}, must be one of: {repr_join(sorted(valid))}"
                raise ValueError(msg)

        return arg
