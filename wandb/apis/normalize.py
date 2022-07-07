"""
normalize.
"""

import ast
from functools import wraps
import sys
from typing import Callable, TypeVar

import requests
from wandb import env
from wandb.errors import CommError
from wandb_gql.client import RetryError

_F = TypeVar("_F", bound=Callable)


def normalize_exceptions(func: _F) -> _F:
    """Function decorator for catching common errors and re-raising as wandb.Error"""

    @wraps(func)
    def wrapper(*args, **kwargs):
        message = "Whoa, you found a bug."
        try:
            return func(*args, **kwargs)
        except requests.HTTPError as err:
            raise CommError(err.response, err)
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
