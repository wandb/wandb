"""normalize."""

import ast
import sys
from functools import wraps
from typing import Callable, TypeVar

import requests
from wandb_gql.client import RetryError

from wandb import env
from wandb.errors import CommError, Error
from wandb.util import parse_backend_error_messages

_F = TypeVar("_F", bound=Callable)


def normalize_exceptions(func: _F) -> _F:
    """Function decorator for catching common errors and re-raising as wandb.Error."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        message = "Whoa, you found a bug."
        try:
            return func(*args, **kwargs)

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

        except RetryError as err:
            if (
                "response" in dir(err.last_exception)
                and err.last_exception.response is not None
            ):
                try:
                    message = err.last_exception.response.json().get(
                        "errors", [{"message": message}]
                    )[0]["message"]
                except ValueError:
                    message = err.last_exception.response.text
            else:
                message = err.last_exception

            if env.is_debug():
                raise err.last_exception.with_traceback(sys.exc_info()[2])
            else:
                raise CommError(message, err.last_exception).with_traceback(
                    sys.exc_info()[2]
                )
        except Error as err:
            raise err
        except Exception as err:
            # gql raises server errors with dict's as strings...
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

    return wrapper
