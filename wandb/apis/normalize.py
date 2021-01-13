# -*- coding: utf-8 -*-
"""
normalize.
"""

import ast
from functools import wraps
import sys

import requests
import six
from wandb import env
from wandb.errors.error import CommError


def normalize_exceptions(func):
    """Function decorator for catching common errors and re-raising as wandb.Error"""

    @wraps(func)
    def wrapper(*args, **kwargs):
        message = "Whoa, you found a bug."
        try:
            return func(*args, **kwargs)
        except requests.HTTPError as err:
            raise CommError(err.response, err)
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
                six.reraise(*sys.exc_info())
            else:
                six.reraise(CommError, CommError(message, err), sys.exc_info()[2])

    return wrapper
