from __future__ import annotations

import json
import logging
import os
from typing import Any

from wandb import env

logger = logging.getLogger(__name__)


try:
    from wandb.vendor.wandb_orjson import orjson

    # Allow disabling orjson for compatibility and safety.
    if not os.environ.get(env.DISABLE_ORJSON):

        def dumps(obj: Any, **kwargs: Any) -> str:
            """Wrapper for <json|orjson>.dumps."""
            cls = kwargs.pop("cls", None)
            try:
                _kwargs = kwargs.copy()
                if cls:
                    _kwargs["default"] = cls.default
                encoded = orjson.dumps(
                    obj, option=orjson.OPT_NON_STR_KEYS, **_kwargs
                ).decode()
            except Exception:
                logger.exception("Error using orjson.dumps")
                if cls:
                    kwargs["cls"] = cls
                encoded = json.dumps(obj, **kwargs)

            return encoded  # type: ignore[no-any-return]

        def dump(obj: Any, fp: Any, **kwargs: Any) -> None:
            """Wrapper for <json|orjson>.dump."""
            cls = kwargs.pop("cls", None)
            try:
                _kwargs = kwargs.copy()
                if cls:
                    _kwargs["default"] = cls.default
                encoded = orjson.dumps(obj, option=orjson.OPT_NON_STR_KEYS, **_kwargs)
                fp.write(encoded)
            except Exception:
                logger.exception("Error using orjson.dump")
                if cls:
                    kwargs["cls"] = cls
                json.dump(obj, fp, **kwargs)

        def loads(obj: str | bytes) -> Any:
            """Wrapper for orjson.loads."""
            try:
                decoded = orjson.loads(obj)
            except Exception:
                logger.exception("Error using orjson.loads")
                decoded = json.loads(obj)

            return decoded

        def load(fp: Any) -> Any:
            """Wrapper for orjson.load."""
            try:
                decoded = orjson.loads(fp.read())
            except Exception:
                logger.exception("Error using orjson.load")
                decoded = json.load(fp)

            return decoded

    else:
        from json import dump, dumps, load, loads  # type: ignore[assignment]

except ImportError:
    from json import dump, dumps, load, loads  # type: ignore[assignment] # noqa: F401
