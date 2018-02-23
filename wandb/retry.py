import datetime
import logging
import os
import random
import time
import traceback

from wandb import util

logger = logging.getLogger(__name__)


def make_printer(msg):
    def printer():
        print(msg)
    return printer


class Retry(object):
    """Creates a retryable version of a function.

    Calling this will call the passed function, retrying if any exceptions in
    retryable_exceptions are caught, with exponential backoff.
    """

    def __init__(self, call_fn, retryable_exceptions=None, error_prefix="wandb network error"):
        self._call_fn = call_fn
        self._error_prefix = error_prefix
        self._retryable_exceptions = retryable_exceptions
        if self._retryable_exceptions is None:
            self._retryable_exceptions = (Exception,)
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
        retry_timedelta = kwargs.pop('retry_timedelta')  # required
        if retry_timedelta is None:
            # retry forever
            retry_timedelta = datetime.timedelta(days=1000000)
        sleep_base = 1
        try:
            sleep_base = kwargs.pop('retry_sleep_base')
        except KeyError:
            pass

        first = True
        sleep = sleep_base
        start_time = datetime.datetime.now()
        now = start_time

        self._num_iter = 0

        while (now - start_time) < retry_timedelta:
            try:
                result = self._call_fn(*args, **kwargs)
                if not first:
                    print('%s resolved after %s, resuming normal operation.' % (
                        self._error_prefix, datetime.datetime.now() - start_time))
                return result
            except self._retryable_exceptions as e:
                if first:
                    logger.error(traceback.format_exc())
                    print(
                        '%s (%s), retrying indefinitely. See %s for full traceback.' % (
                            self._error_prefix, e.__class__.__name__, util.get_log_file_path()))
                if os.getenv('WANDB_DEBUG'):
                    traceback.print_exc()
            first = False
            time.sleep(sleep + random.random() * 0.25 * sleep)
            sleep *= 2
            if sleep > 3600:
                sleep = 3600
            now = datetime.datetime.now()

            self._num_iter += 1
