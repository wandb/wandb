"""Reusable validators for MongoDB-style filter dicts."""

from __future__ import annotations

from typing import Any

from pydantic.dataclasses import dataclass as pydantic_dataclass

from .filterutils import iter_fields, parse_filter


@pydantic_dataclass(frozen=True, slots=True)
class FilterArg:
    """Validates a MongoDB-style filter dict."""

    allowed: tuple[str, ...] | None = None
    """Allowed field names, if set."""

    def __call__(self, arg: dict[str, Any]) -> dict[str, Any]:
        if (allowed := self.allowed) is None:
            return arg

        # For dotted paths, check only the top-level name.
        #   e.g. "metadata.foo" -> "metadata"
        seen = set(s.split(".")[0] for s in iter_fields(parse_filter(arg)))
        if invalid := seen.difference(allowed):
            invalid_repr = ", ".join(map(repr, sorted(invalid)))
            allowed_repr = ", ".join(map(repr, sorted(allowed)))

            msg = f"Invalid filter field(s) {invalid_repr}, must be one of: {allowed_repr}"
            raise ValueError(msg)

        return arg
