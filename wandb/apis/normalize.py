"""normalize."""

import ast
import sys
from functools import wraps
from typing import Callable, List, TypeVar

import requests
from wandb_gql.client import RetryError

from wandb import env
from wandb.errors import CommError, Error

_F = TypeVar("_F", bound=Callable)


def parse_backend_error_messages(response: requests.Response) -> List[str]:
    errors = []
    try:
        data = response.json()
    except ValueError:
        return errors

    if "errors" in data and isinstance(data["errors"], list):
        for error in data["errors"]:
            # Our tests and potentially some api endpoints return a string error?
            if isinstance(error, str):
                error = {"message": error}
            if "message" in error:
                errors.append(error["message"])
    return errors


def normalize_exceptions(func: _F) -> _F:
    """Function decorator for catching common errors and re-raising as wandb.Error."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        message = "Whoa, you found a bug."
        try:
            return func(*args, **kwargs)
        except requests.HTTPError as error:
            errors = parse_backend_error_messages(error.response)
            if errors:
                message = " ".join(errors)
                message += (
                    f" (Error {error.response.status_code}: {error.response.reason})"
                )
            else:
                message = error.response
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
