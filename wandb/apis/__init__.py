import ast
from functools import wraps
import requests
import sys
import os

from gql.client import RetryError
import six
from wandb import Error
import wandb.env


class Progress(object):
    """A helper class for displaying progress"""

    def __init__(self, file, callback=None):
        self.file = file
        if callback is None:
            def callback(bites, total): return (bites, total)
        self.callback = callback
        self.bytes_read = 0
        self.len = os.fstat(file.fileno()).st_size

    def read(self, size=-1):
        """Read bytes and call the callback"""
        bites = self.file.read(size)
        self.bytes_read += len(bites)
        self.callback(len(bites), self.bytes_read)
        return bites


class CommError(Error):
    """Error communicating with W&B"""

    def __init__(self, msg, exc=None):
        super(CommError, self).__init__(msg)
        self.exc = exc


class UsageError(Error):
    """API Usage Error"""
    pass


def normalize_exceptions(func):
    """Function decorator for catching common errors and re-raising as wandb.Error"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        message = "Whoa, you found a bug."
        try:
            return func(*args, **kwargs)
        except requests.HTTPError as err:
            raise CommError(err.response, err)
        except RetryError as err:
            if "response" in dir(err.last_exception) and err.last_exception.response is not None:
                try:
                    message = err.last_exception.response.json().get(
                        'errors', [{'message': message}])[0]['message']
                except ValueError:
                    message = err.last_exception.response.text
            else:
                message = err.last_exception

            six.reraise(CommError, CommError(message, err.last_exception), sys.exc_info()[2])
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
            if wandb.env.is_debug():
                six.reraise(*sys.exc_info())
            else:
                six.reraise(CommError, CommError(message, err), sys.exc_info()[2])
    return wrapper


from .file_stream import FileStreamApi
from .internal import Api as InternalApi
from .public import Api as PublicApi
