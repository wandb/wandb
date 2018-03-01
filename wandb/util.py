import base64
import errno
import hashlib
import json
import logging
import os
from six.moves import queue
import requests
import shlex
import subprocess
import threading
import time

from wandb import io_wrap

logger = logging.getLogger(__name__)

# TODO: get rid of this
try:
    import numpy as np
except ImportError:
    pass


class WandBJSONEncoder(json.JSONEncoder):
    """A JSON Encoder that handles some extra types."""

    def default(self, obj):
        # TODO: Some of this is just guessing. Be smarter.
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.generic):
            return np.asscalar(obj)
        if isinstance(obj, bytes):
            return obj.decode('utf-8')
        return json.JSONEncoder.default(self, obj)


def json_dumps_safer(obj, **kwargs):
    """Convert obj to json, with some extra encodable types."""
    return json.dumps(obj, cls=WandBJSONEncoder, **kwargs)


def make_json_if_not_number(v):
    """If v is not a basic type convert it to json."""
    if isinstance(v, (float, int)):
        return v
    return json_dumps_safer(v)


def mkdir_exists_ok(path):
    try:
        os.makedirs(path)
        return True
    except OSError as exc:
        if exc.errno == errno.EEXIST and os.path.isdir(path):
            return False
        else:
            raise


def request_with_retry(func, *args, **kwargs):
    """Perform a requests http call, retrying with exponetial backoff.

    Args:
        func: An http-requesting function to call, like requests.post
        retries: Maximum retries before giving up.
        *args: passed through to func
        **kwargs: passed through to func
    """
    retries = kwargs.get('retries', 5)
    retry_delay = 2
    retry_count = 0
    while True:
        try:
            response = func(*args, **kwargs)
            response.raise_for_status()
            return True
        except (requests.exceptions.ConnectionError,
                requests.exceptions.HTTPError,  # XXX 500s aren't retryable
                requests.exceptions.Timeout) as e:
            logger.warning('requests_with_retry encountered retryable exception: %s. args: %s, kwargs: %s',
                           e, args, kwargs)
            if retry_count == retries:
                return e
            retry_count += 1
            time.sleep(retry_delay)
            retry_delay *= 2
        except requests.exceptions.RequestException as e:
            logger.error(response.json()['error'])  # XXX clean this up
            logger.exception(
                'requests_with_retry encountered unretryable exception: %s', e)
            return e


def find_runner(program):
    """Return a command that will run program.

    Args:
        program: The string name of the program to try to run.
    Returns:
        commandline list of strings to run the program (eg. with subprocess.call()) or None
    """
    if os.path.isfile(program) and not os.access(program, os.X_OK):
        # program is a path to a non-executable file
        try:
            opened = open(program)
        except PermissionError:
            return None
        first_line = opened.readline().strip()
        if first_line.startswith('#!'):
            return shlex.split(first_line[2:])
        if program.endswith('.py'):
            return ['python']
    return None


def downsample(values, target_length):
    """Downsamples 1d values to target_length, including start and end.

    Algorithm just rounds index down.

    Values can be any sequence, including a generator.
    """
    assert target_length > 1
    values = list(values)
    if len(values) < target_length:
        return values
    ratio = float(len(values) - 1) / (target_length - 1)
    result = []
    for i in range(target_length):
        result.append(values[int(i * ratio)])
    return result


def md5_file(path):
    hash_md5 = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return base64.b64encode(hash_md5.digest()).decode('ascii')


def get_log_file_path():
    root_handlers = logger.root.handlers
    if root_handlers and "baseFilename" in dir(root_handlers[0]):
        return os.path.relpath(root_handlers[0].baseFilename, os.getcwd())
    else:
        return '<unknown>'


def read_many_from_queue(q, max_items, queue_timeout):
    try:
        item = q.get(True, queue_timeout)
    except queue.Empty:
        return []
    items = [item]
    for i in range(max_items):
        try:
            item = q.get_nowait()
        except queue.Empty:
            return items
        items.append(item)
    return items
