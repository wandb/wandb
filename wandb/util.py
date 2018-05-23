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
import sys
import threading
import time
import random
import textwrap
import click
import stat

import wandb
from wandb import io_wrap
from wandb import wandb_dir

logger = logging.getLogger(__name__)

# TODO: get rid of this
try:
    import numpy as np
except ImportError:
    pass

MAX_SLEEP_SECONDS = 60 * 5


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


def write_settings(entity, project, url):
    if not os.path.isdir(wandb_dir()):
        os.mkdir(wandb_dir())
    with open(os.path.join(wandb_dir(), 'settings'), "w") as file:
        print('[default]', file=file)
        print('entity: {}'.format(entity), file=file)
        print('project: {}'.format(project), file=file)
        print('base_url: {}'.format(url), file=file)


def write_netrc(host, entity, key):
    """Add our host and key to .netrc"""
    if len(key) != 40:
        click.secho(
            'API-key must be exactly 40 characters long: %s (%s chars)' % (key, len(key)))
        return None
    try:
        print("Appending key to your netrc file: %s" %
              os.path.expanduser('~/.netrc'))
        normalized_host = host.split("/")[-1].split(":")[0]
        machine_line = 'machine %s' % normalized_host
        path = os.path.expanduser('~/.netrc')
        orig_lines = None
        try:
            with open(path) as f:
                orig_lines = f.read().strip().split('\n')
        except (IOError, OSError) as e:
            pass
        with open(path, 'w') as f:
            if orig_lines:
                # delete this machine from the file if it's already there.
                skip = 0
                for line in orig_lines:
                    if machine_line in line:
                        skip = 2
                    elif skip:
                        skip -= 1
                    else:
                        f.write('%s\n' % line)
            f.write(textwrap.dedent("""\
            machine {host}
              login {entity}
              password {key}
            """).format(host=normalized_host, entity=entity, key=key))
        os.chmod(os.path.expanduser('~/.netrc'),
                 stat.S_IRUSR | stat.S_IWUSR)
        return True
    except IOError as e:
        click.secho("Unable to read ~/.netrc", fg="red")
        return None


def request_with_retry(func, *args, **kwargs):
    """Perform a requests http call, retrying with exponential backoff.

    Args:
        func: An http-requesting function to call, like requests.post
        max_retries: Maximum retries before giving up. By default we retry 30 times in ~2 hours before dropping the chunk
        *args: passed through to func
        **kwargs: passed through to func
    """
    max_retries = kwargs.pop('max_retries', 30)
    sleep = 2
    retry_count = 0
    while True:
        try:
            response = func(*args, **kwargs)
            response.raise_for_status()
            return response
        except (requests.exceptions.ConnectionError,
                requests.exceptions.HTTPError,  # XXX 500s aren't retryable
                requests.exceptions.Timeout) as e:
            if retry_count == max_retries:
                return e
            retry_count += 1
            delay = sleep + random.random() * 0.25 * sleep
            if isinstance(e, requests.exceptions.HTTPError) and e.response.status_code == 429:
                logger.info(
                    "Rate limit exceeded, retrying in %s seconds" % delay)
            else:
                logger.warning('requests_with_retry encountered retryable exception: %s. args: %s, kwargs: %s',
                               e, args, kwargs)
            time.sleep(delay)
            sleep *= 2
            if sleep > MAX_SLEEP_SECONDS:
                sleep = MAX_SLEEP_SECONDS
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
            return [sys.executable]
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
    return wandb.log_fname


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
