"""Reusable validators for MongoDB-style filter dicts."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import KW_ONLY, dataclass, field
from operator import itemgetter
from types import MappingProxyType
from typing import Any, TypeAlias

from pydantic import GetCoreSchemaHandler
from pydantic_core import CoreSchema
from pydantic_core.core_schema import no_info_after_validator_function
from typing_extensions import assert_never

from wandb._strutils import repr_join

from .filterutils import iter_fields, parse_filter

FieldName: TypeAlias = str
OperandTransform: TypeAlias = Callable[[Any], Any]


@dataclass(frozen=True, slots=True)
class FilterValidator:
    """Pydantic metadata that validates and normalizes filter field names."""

    valid: frozenset[FieldName] | None = None
    """Allowed names, or aliases mapped to canonical serialized names."""

    _: KW_ONLY

    transforms: MappingProxyType[FieldName, OperandTransform] = field(
        default_factory=lambda: MappingProxyType({})
    )
    """Canonical field names and transformations for their operands."""

    aliases: MappingProxyType[FieldName, FieldName] = field(init=False)
    """Read-only accepted-to-canonical aliases derived from ``valid``."""

    def __post_init__(self) -> None:
        # Empty collections are treated as None (no restrictions on valid names)
        match self.valid:
            case dict(valid):
                aliases = dict(valid)
            case valid:
                aliases = {name: name for name in sorted(valid or ())}
        object.__setattr__(self, "aliases", MappingProxyType(aliases))

        valid = frozenset(valid) if valid else None
        object.__setattr__(self, "valid", valid)
        object.__setattr__(self, "transforms", MappingProxyType(dict(self.transforms)))

    def __hash__(self) -> int:
        # Mapping proxies are immutable but unhashable, so hash their contents.
        return hash(
            (
                self.valid,
                frozenset(self.aliases.items()),
                frozenset(self.transforms.items()),
            )
        )

    def __get_pydantic_core_schema__(
        self, source_type: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        return no_info_after_validator_function(self.validate, handler(source_type))

    def validate(self, raw: dict[str, Any]) -> dict[str, Any]:
        parsed = parse_filter(raw)
        if valid := self.valid:
            invalid = {
                root
                for field in iter_fields(parsed)
                if (root := field.partition(".")[0]) not in valid
            }
            if invalid:
                msg = f"Invalid filter fields: {repr_join(sorted(invalid))}; must be one of: {repr_join(sorted(valid))}"
                raise ValueError(msg)

        return self.transform(raw)

    def transform(self, raw: dict[str, Any]) -> dict[str, Any]:
        new_items = tuple(self._transform_item(item) for item in raw.items())
        new_dict = dict(new_items)

        # Alias definitions are intentionally many-to-one. A collision is invalid
        # only when one filter object uses multiple aliases for the same field.
        if len(new_dict) != len(new_items):
            new_keys = map(itemgetter(0), new_items)
            dup_keys = {key for key, count in Counter(new_keys).items() if count > 1}
            msg = f"Duplicate fields: {repr_join(sorted(dup_keys))}"
            raise ValueError(msg)

        return new_dict

    def _transform_item(self, item: tuple[str, Any]) -> tuple[str, Any]:
        match item:
            case (("$and" | "$or" | "$nor") as key, list(children)):
                return key, list(map(self.transform, children))

            case ("$not" as key, dict(child)):
                return key, self.transform(child)

            case (str(op), _) if op.startswith("$"):
                return item

            case (str(field), val):
                root, sep, suffix = field.partition(".")
                field = f"{self.aliases.get(root) or root}{sep}{suffix}"
                val = fn(val) if (fn := self.transforms.get(field)) else val
                return field, val

            case _:
                assert_never(item)
