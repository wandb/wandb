import json
import logging
import math
import os
from typing import Any, Union

logger = logging.getLogger(__name__)


if "_WANDB_USE_JSON" not in os.environ:
    import orjson  # type: ignore

    def _create_orjson_fragments(obj: Any) -> Any:
        """Create orjson fragments for non-serializable objects.

        Orjson fragments are not serialized by orjson.
        So this allows us to still support non-standard json types. (inf, -inf, nan)
        """
        if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
            return orjson.Fragment(json.dumps(obj))
        return obj

    def _walk_and_create_fragments(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: _walk_and_create_fragments(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [_walk_and_create_fragments(v) for v in obj]
        else:
            return _create_orjson_fragments(obj)

    # additional safeguard for now
    def dumps(obj: Any, **kwargs: Any) -> str:
        """Wrapper for <json|orjson>.dumps."""
        cls = kwargs.pop("cls", None)
        try:
            obj = _walk_and_create_fragments(obj)

            _kwargs = kwargs.copy()
            if cls:
                _kwargs["default"] = cls.default
            encoded = orjson.dumps(
                obj,
                option=orjson.OPT_NON_STR_KEYS,
                **_kwargs,
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

    def loads(obj: Union[str, bytes]) -> Any:
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
    from json import dump, dumps, load, loads  # type: ignore[assignment] # noqa: F401
