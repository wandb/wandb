"""normalize."""

from __future__ import annotations

import ast
import sys
from collections.abc import Callable
from functools import wraps
from typing import TYPE_CHECKING, TypeVar, cast

from wandb import env
from wandb.errors import CommError, Error
from wandb.sdk.lib.service.service_connection import WandbApiFailedError
from wandb.util import parse_backend_error_messages

if TYPE_CHECKING:
    import requests

_F = TypeVar("_F", bound=Callable)


def _as_requests_http_error(err: Exception) -> requests.HTTPError | None:
    """Returns the error if it is a requests HTTPError, else None.

    Checked without importing the requests library: if it was never imported,
    then nothing could have raised its HTTPError.
    """
    requests = sys.modules.get("requests")

    if requests and isinstance(err, requests.HTTPError):
        return err

    return None


def _http_error_message(error: requests.HTTPError) -> str:
    errors = parse_backend_error_messages(error.response)
    status = error.response.status_code

    if errors:
        return f"HTTP {status}: {'; '.join(errors)}"
    elif error.response.text:
        return f"HTTP {status}: {error.response.text}"
    elif error.response.reason:
        # Visually different to distinguish backend errors from
        # standard HTTP status descriptions.
        return f"HTTP {status} ({error.response.reason})"
    else:
        return f"HTTP {status}"


def normalize_exceptions(func: _F) -> _F:
    """Function decorator for catching common errors and re-raising as wandb.Error."""

    @wraps(func)
    def wrapper(*args, **kwargs):
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

        except Error:
            raise
        except Exception as err:
            if http_error := _as_requests_http_error(err):
                raise CommError(_http_error_message(http_error), http_error)

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
