"""normalize."""

from __future__ import annotations

import ast
import sys
from collections.abc import Callable
from functools import wraps
from typing import TypeVar, cast

from wandb import env
from wandb.errors import CommError, Error
from wandb.sdk.lib.service.service_connection import WandbApiFailedError
from wandb.util import parse_backend_error_messages

_F = TypeVar("_F", bound=Callable)


def normalize_exceptions(func: _F) -> _F:
    """Function decorator for catching common errors and re-raising as wandb.Error."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        import requests

        message = "Whoa, you found a bug."
        try:
            return func(*args, **kwargs)

        except WandbApiFailedError as err:
            if err.response is not None and err.response.message:
                message = err.response.message
            else:
                message = str(err) or message
            if env.is_debug():
                raise
            raise CommError(message, err) from err

        except requests.HTTPError as error:
            errors = parse_backend_error_messages(error.response)
            status = error.response.status_code

            if errors:
                message = f"HTTP {status}: {'; '.join(errors)}"
            elif error.response.text:
                message = f"HTTP {status}: {error.response.text}"
            elif error.response.reason:
                # Visually different to distinguish backend errors from
                # standard HTTP status descriptions.
                message = f"HTTP {status} ({error.response.reason})"
            else:
                message = f"HTTP {status}"

            raise CommError(message, error)

        except Error:
            raise
        except Exception as err:
            if len(err.args) > 0:
                payload = err.args[0]
            else:
                payload = err
            if str(payload).startswith("{"):
                message = ast.literal_eval(str(payload))["message"]
            else:
                message = str(err)
            if env.is_debug():
                raise
            else:
                raise CommError(message, err).with_traceback(sys.exc_info()[2])

    return cast(_F, wrapper)
