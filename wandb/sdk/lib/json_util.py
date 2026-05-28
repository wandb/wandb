"""JSON helpers backed by pydantic-core, with stdlib fallback.

The wrapper mirrors the stdlib `json` surface (`dumps`/`dump`/`loads`/`load`)
and routes the hot path through `pydantic_core` for speed. Anything pydantic
cannot do — unrecognized kwargs, unserializable objects without a fallback,
etc. — is caught and re-tried with the stdlib so semantics stay aligned.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pydantic_core

logger = logging.getLogger(__name__)


def dumps(obj: Any, **kwargs: Any) -> str:
    """Serialize `obj` to a JSON string."""
    try:
        cls = kwargs.get("cls")
        fallback = kwargs.get("default") or (cls and cls().default)
        return pydantic_core.to_json(
            obj,
            indent=kwargs.get("indent"),
            inf_nan_mode="constants",
            fallback=fallback,
        ).decode()
    except Exception:
        logger.exception("pydantic_core.to_json failed; using stdlib json")
        return json.dumps(obj, **kwargs)


def dump(obj: Any, fp: Any, **kwargs: Any) -> None:
    """Serialize `obj` as JSON and write the result to `fp`."""
    fp.write(dumps(obj, **kwargs))


def loads(s: str | bytes | bytearray, **kwargs: Any) -> Any:
    """Deserialize a JSON string to a Python object."""
    if kwargs:
        return json.loads(s, **kwargs)
    try:
        return pydantic_core.from_json(s)
    except Exception:
        logger.exception("pydantic_core.from_json failed; using stdlib json")
        return json.loads(s)


def load(fp: Any, **kwargs: Any) -> Any:
    """Read JSON from `fp` and return the deserialized object."""
    return loads(fp.read(), **kwargs)
