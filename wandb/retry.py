import datetime
import functools
import logging
import os
import random
import time
import traceback
import weakref

import wandb
import wandb.env
from wandb import util

logger = logging.getLogger(__name__)


def make_printer(msg):
    def printer():
        print(msg)
    return printer


class TransientException(Exception):
    """Exception type designated for errors that may only be temporary

    Can have its own message and/or wrap another exception.
    """
    def __init__(self, msg=None, exc=None):
        super(TransientException, self).__init__(msg)
        self.message = msg
        self.exception = exc


class Retry(object):
    """Creates a retryable version of a function.

    Calling this will call the passed function, retrying if any exceptions in
    retryable_exceptions are caught, with exponential backoff.
    """

    MAX_SLEEP_SECONDS = 5 * 60

    def __init__(self, call_fn, retry_timedelta=None, num_retries=None,
                 retryable_exceptions=None, error_prefix="Network error"):
        self._call_fn = call_fn
        self._error_prefix = error_prefix
        self._retry_timedelta = retry_timedelta
        self._num_retries = num_retries
        self._retryable_exceptions = retryable_exceptions
        if self._retryable_exceptions is None:
            self._retryable_exceptions = (TransientException,)
        self._index = 0

    @property
    def num_iters(self):
        """The number of iterations the previous __call__ retried."""
        return self._num_iter

    def __call__(self, *args, **kwargs):
        """Call the wrapped function, with retries.

        Args:
           retry_timedelta (kwarg): amount of time to retry before giving up.
           sleep_base (kwarg): amount of time to sleep upon first failure, all other sleeps
               are derived from this one.
        """

        retry_timedelta = kwargs.pop('retry_timedelta', self._retry_timedelta)
        if retry_timedelta is None:
            retry_timedelta = datetime.timedelta(days=1000000)

        num_retries = kwargs.pop('num_retries', self._num_retries)
        if num_retries is None:
            num_retries = 1000000

        if os.environ.get('WANDB_TEST'):
            num_retries = 0

        sleep_base = kwargs.pop('retry_sleep_base', 1)

        first = True
        sleep = sleep_base
        start_time = datetime.datetime.now()
        now = start_time

        self._num_iter = 0

        while True:
            try:
                result = self._call_fn(*args, **kwargs)
                if not first:
                    wandb.termlog('%s resolved after %s, resuming normal operation.' % (
                        self._error_prefix, datetime.datetime.now() - start_time))
                return result
            except self._retryable_exceptions as e:
                if (datetime.datetime.now() - start_time >= retry_timedelta
                        or self._num_iter >= num_retries):
                    raise
                if self._num_iter == 2:
                    logger.exception('Retry attempt failed:')
                    wandb.termlog(
                        '%s (%s), entering retry loop. See %s for full traceback.' % (
                            self._error_prefix, e.__class__.__name__, util.get_log_file_path()))
                if wandb.env.is_debug():
                    traceback.print_exc()
            first = False
            time.sleep(sleep + random.random() * 0.25 * sleep)
            sleep *= 2
            if sleep > self.MAX_SLEEP_SECONDS:
                sleep = self.MAX_SLEEP_SECONDS
            now = datetime.datetime.now()

            self._num_iter += 1


def retriable(*args, **kargs):
    def decorator(fn):
        retrier = Retry(fn, *args, **kargs)
        @functools.wraps(fn)
        def wrapped_fn(*args, **kargs):
            return retrier(*args, **kargs)
        return wrapped_fn
    return decorator

