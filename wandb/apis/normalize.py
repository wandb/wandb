# -*- coding: utf-8 -*-
"""
normalize.
"""

from functools import wraps
import sys

import requests
import six
from wandb import env
from wandb.errors import CommError


def normalize_exceptions(func):
    """Function decorator for catching common errors and re-raising as wandb.CommError"""

    @wraps(func)
    def wrapper(*args, **kwargs):
        message = "Whoa, you found a bug."
        try:
            return func(*args, **kwargs)
        except requests.HTTPError as err:
            try:
                message = err.response.json().get(
                    "errors", [{"message": "Generic HTTP error"}]
                )[0]["message"]
            except ValueError:
                message = "Generic HTTP error"
            raise CommError(message, err)
        except Exception as err:
            message = str(err)
            if env.is_debug():
                six.reraise(*sys.exc_info())
            else:
                six.reraise(CommError, CommError(message, err), sys.exc_info()[2])

    return wrapper
