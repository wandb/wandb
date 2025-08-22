import json
import logging
import os
from typing import Any, Union

logger = logging.getLogger(__name__)


try:
    import orjson  # type: ignore

    # todo: orjson complies with the json standard and does not support
    #  NaN, Infinity, and -Infinity. Should be fixed in the future.

    # additional safeguard for now
    if os.environ.get("_WANDB_ORJSON"):

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
        from json import dump, dumps, load, loads  # type: ignore[assignment]

except ImportError:
    from json import dump, dumps, load, loads  # type: ignore[assignment] # noqa: F401
