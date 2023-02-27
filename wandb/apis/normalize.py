"""normalize."""

import ast
import sys
from functools import wraps
from typing import Callable, TypeVar

import requests
from wandb_gql.client import RetryError

from wandb import env
from wandb.errors import CommError
from wandb.sdk.lib.mailbox import ContextCancelledError

_F = TypeVar("_F", bound=Callable)


def normalize_exceptions(func: _F) -> _F:
    """Function decorator for catching common errors and re-raising as wandb.Error."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        message = "Whoa, you found a bug."
        try:
            return func(*args, **kwargs)
        except requests.HTTPError as error:
            try:
                data = error.response.json()
            except ValueError:
                message = error.response
            else:
                # This else block tries to parse error messages that come from the server (gorilla)
                message = ""
                if "errors" in data and isinstance(data["errors"], list):
                    for err in data["errors"]:
                        # Our tests and potentially some api endpoints return a string error?
                        if isinstance(err, str):
                            err = {"message": err}
                        if "message" in err:
                            message += err["message"]
                    if message:
                        message += f" (Error {error.response.status_code}: {error.response.reason})"
            raise CommError(message or error.response, error)
        except ContextCancelledError as err:
            raise err
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
        except CommError as err:
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
