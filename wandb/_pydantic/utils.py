"""Internal utilities for working with Pydantic types and data."""

from __future__ import annotations

import json
import sys
from contextlib import suppress
from typing import Any, Type

import pydantic
from pydantic import BaseModel, ValidationError
from typing_extensions import TypeAlias

PYTHON_VERSION = sys.version_info

pydantic_major, *_ = pydantic.VERSION.split(".")
IS_PYDANTIC_V2: bool = int(pydantic_major) >= 2


BaseModelType: TypeAlias = Type[BaseModel]


def gql_typename(cls: type[BaseModel]) -> str:
    """Get the GraphQL typename for a Pydantic model."""
    if (field := cls.model_fields.get("typename__")) and (typename := field.default):
        return typename
    raise TypeError(f"Cannot extract GraphQL typename from: {cls.__qualname__!r}.")


if IS_PYDANTIC_V2:
    import pydantic_core  # pydantic_core is only installed by pydantic v2

    def from_json(s: str) -> Any:
        """Quickly deserialize a JSON string to a Python object."""
        return pydantic_core.from_json(s)

    def to_json(v: Any) -> str:
        """Quickly serialize a (possibly Pydantic) object to a JSON string."""
        return pydantic_core.to_json(v, by_alias=True, round_trip=True).decode("utf-8")

    def pydantic_isinstance(
        v: Any, classinfo: BaseModelType | tuple[BaseModelType, ...]
    ) -> bool:
        """Return True if the object could be parsed into the given Pydantic type.

        This is like a more lenient version of `isinstance()` for use with Pydantic.
        In Pydantic v2, should be fast since the underlying implementation is in Rust,
        and it may be preferable over `try:...except ValidationError:...`.

        See: https://docs.pydantic.dev/latest/api/pydantic_core/#pydantic_core.SchemaValidator.isinstance_python
        """
        if isinstance(classinfo, tuple):
            return any(
                cls.__pydantic_validator__.isinstance_python(v) for cls in classinfo
            )
        cls = classinfo
        return cls.__pydantic_validator__.isinstance_python(v)

else:
    # Pydantic v1 fallback implementations.
    # These may be noticeably slower, but their primary goal is to ensure
    # compatibility with Pydantic v1 so long as we need to support it.

    from pydantic.json import pydantic_encoder  # Only valid in pydantic v1

    def from_json(s: str) -> Any:
        return json.loads(s)

    def to_json(v: Any) -> str:
        return json.dumps(v, default=pydantic_encoder)

    def pydantic_isinstance(
        v: Any, classinfo: BaseModelType | tuple[BaseModelType, ...]
    ) -> bool:
        classes = classinfo if isinstance(classinfo, tuple) else (classinfo,)
        for cls in classes:
            with suppress(ValidationError):
                cls.model_validate(v)
                return True
        return False
