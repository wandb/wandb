"""Miscellaneous utilities for working with Pydantic types and data."""

from __future__ import annotations

import json
import sys
from contextlib import suppress
from importlib.metadata import version
from typing import Any, TypeVar

import pydantic
from pydantic import BaseModel

PYTHON_VERSION = sys.version_info

pydantic_major_version, *_ = version(pydantic.__name__).split(".")
IS_PYDANTIC_V2: bool = int(pydantic_major_version) >= 2

BaseModelT = TypeVar("BaseModelT", bound=BaseModel)

if IS_PYDANTIC_V2:
    import pydantic_core  # Only installed by pydantic v2

    def to_json(v: Any) -> str:
        """Serialize a Python object to a JSON string."""
        return pydantic_core.to_json(v, by_alias=True, round_trip=True).decode("utf-8")

    def pydantic_isinstance(v: Any, cls: type[BaseModelT]) -> bool:
        """Return True if the Python object can be validated (parsed) as a specific Pydantic type."""
        # Underlying implementation should be in Rust,
        # so may be preferable to `try...except ValidationError`
        # https://docs.pydantic.dev/latest/api/pydantic_core/#pydantic_core.SchemaValidator.isinstance_python
        return cls.__pydantic_validator__.isinstance_python(v)
else:
    from pydantic import ValidationError
    from pydantic.json import pydantic_encoder  # Only valid in pydantic v1

    def to_json(v: Any) -> str:
        """Serialize a Python object to a JSON string."""
        return json.dumps(v, default=pydantic_encoder)

    # This is really awkward and/or slow, but we need a way to keep the code v1 compatible
    def pydantic_isinstance(v: Any, cls: type[BaseModelT]) -> bool:
        with suppress(ValidationError):
            cls.model_validate(v)
            return True
        return False
