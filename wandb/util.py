import errno
import json
import logging
import os
from six.moves import queue
import requests
import subprocess
import threading
import time

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
    except OSError as exc:
        if exc.errno == errno.EEXIST and os.path.isdir(path):
            pass
        else:
            raise


class SafeSubprocess(object):
    def __init__(self, args, env=None, read_output=False):
        self._args = args
        self._env = env
        self._read_output = read_output
        self._stdout = queue.Queue()
        self._stderr = queue.Queue()
        self._popen = None
        self._stdout_thread = None
        self._stderr_thread = None

    def run(self):
        if self._read_output:
            self._popen = subprocess.Popen(
                self._args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self._env)
            self._stdout_thread = self._spawn_reader_thread(
                self._popen.stdout, self._stdout)
            self._stderr_thread = self._spawn_reader_thread(
                self._popen.stderr, self._stderr)
        else:
            self._popen = subprocess.Popen(self._args, env=self._env)

    def _spawn_reader_thread(self, filelike, out_queue):
        def _reader_thread(filelike, out_queue):
            while True:
                out = filelike.read(64).decode('utf-8')
                if not out:
                    break
                out_queue.put(out)

        threading.Thread(target=_reader_thread,
                         args=(filelike, out_queue)).start()

    def _read(self, rqueue):
        try:
            return rqueue.get(False)
        except queue.Empty:
            return None

    def _read_all(self, rqueue):
        reads = []
        while True:
            got = self._read(rqueue)
            if got is None:
                break
            reads.append(got)
        return reads

    def _read_stdout(self):
        return self._read_all(self._stdout)

    def _read_stderr(self):
        return self._read_all(self._stderr)

    def poll(self):
        if self._read_output:
            return self._popen.poll(), self._read_stdout(), self._read_stderr()
        else:
            return self._popen.poll()


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
                requests.exceptions.HTTPError,
                requests.exceptions.Timeout) as e:
            logger.warning('requests_with_retry encountered retryable exception: %s. args: %s, kwargs: %s',
                           e, args, kwargs)
            if retry_count == retries:
                return e
            retry_count += 1
            time.sleep(retry_delay)
            retry_delay *= 2
        except requests.exceptions.RequestException as e:
            logger.error(
                'requests_with_retry encountered unretryable exception: %s', e)
            return e
