import datetime
import functools
import logging
import os
import random
import time
from typing import Any, Callable, Generic, Optional, Tuple, Type, TypeVar

from requests import HTTPError
import wandb
from wandb.util import CheckRetryFnType


logger = logging.getLogger(__name__)


class TransientError(Exception):
    """Exception type designated for errors that may only be temporary

    Can have its own message and/or wrap another exception.
    """

    def __init__(
        self, msg: Optional[str] = None, exc: Optional[BaseException] = None
    ) -> None:
        super().__init__(msg)
        self.message = msg
        self.exception = exc


_R = TypeVar("_R")


class Retry(Generic[_R]):
    """Creates a retryable version of a function.

    Calling this will call the passed function, retrying if any exceptions in
    retryable_exceptions are caught, with exponential backoff.
    """

    MAX_SLEEP_SECONDS = 5 * 60

    def __init__(
        self,
        call_fn: Callable[..., _R],
        retry_timedelta: Optional[datetime.timedelta] = None,
        num_retries: Optional[int] = None,
        check_retry_fn: CheckRetryFnType = lambda e: True,
        retryable_exceptions: Optional[Tuple[Type[Exception], ...]] = None,
        error_prefix: str = "Network error",
        retry_callback: Optional[Callable[[int, str], Any]] = None,
        sleep_fn_for_testing: Callable[[float], None] = time.sleep,
        datetime_now_fn_for_testing: Callable[
            [], datetime.datetime
        ] = datetime.datetime.now,
    ) -> None:
        self._call_fn = call_fn
        self._check_retry_fn = check_retry_fn
        self._error_prefix = error_prefix
        self._last_print = datetime.datetime.now() - datetime.timedelta(minutes=1)
        self._retry_timedelta = retry_timedelta
        self._num_retries = num_retries
        if retryable_exceptions is not None:
            self._retryable_exceptions = retryable_exceptions
        else:
            self._retryable_exceptions = (TransientError,)
        self._index = 0
        self.retry_callback = retry_callback
        self._sleep_fn = sleep_fn_for_testing
        self._datetime_now_fn = datetime_now_fn_for_testing

    @property
    def num_iters(self) -> int:
        """The number of iterations the previous __call__ retried."""
        return self._num_iter

    def __call__(self, *args: Any, **kwargs: Any) -> _R:
        """Call the wrapped function, with retries.

        Arguments:
           retry_timedelta (kwarg): amount of time to retry before giving up.
           sleep_base (kwarg): amount of time to sleep upon first failure, all other sleeps
               are derived from this one.
        """

        retry_timedelta = kwargs.pop("retry_timedelta", self._retry_timedelta)
        if retry_timedelta is None:
            retry_timedelta = datetime.timedelta(days=365)

        num_retries = kwargs.pop("num_retries", self._num_retries)
        if num_retries is None:
            num_retries = 1000000

        if os.environ.get("WANDB_TEST"):
            num_retries = 0

        sleep_base: float = kwargs.pop("retry_sleep_base", 1)

        # an extra function to allow performing more logic on the filtered exception
        check_retry_fn: CheckRetryFnType = kwargs.pop(
            "check_retry_fn", self._check_retry_fn
        )

        sleep = sleep_base
        now = self._datetime_now_fn()
        start_time = now
        start_time_triggered = None

        self._num_iter = 0

        while True:
            try:
                result = self._call_fn(*args, **kwargs)
                # Only print resolved attempts once every minute
                if self._num_iter > 2 and now - self._last_print > datetime.timedelta(
                    minutes=1
                ):
                    self._last_print = self._datetime_now_fn()
                    if self.retry_callback:
                        self.retry_callback(
                            200,
                            "{} resolved after {}, resuming normal operation.".format(
                                self._error_prefix, self._datetime_now_fn() - start_time
                            ),
                        )
                return result
            except self._retryable_exceptions as e:
                # if the secondary check fails, re-raise
                retry_timedelta_triggered = check_retry_fn(e)
                if not retry_timedelta_triggered:
                    raise

                # always enforce num_retries no matter which type of exception was seen
                if self._num_iter >= num_retries:
                    raise

                now = self._datetime_now_fn()

                # handle a triggered secondary check which could have a shortened timeout
                if isinstance(retry_timedelta_triggered, datetime.timedelta):
                    # save the time of the first secondary trigger
                    if not start_time_triggered:
                        start_time_triggered = now

                    # make sure that we havent run out of time from secondary trigger
                    if now - start_time_triggered >= retry_timedelta_triggered:
                        raise

                # always enforce the default timeout from start of retries
                if now - start_time >= retry_timedelta:
                    raise

                if self._num_iter == 2:
                    logger.exception("Retry attempt failed:")
                    if (
                        isinstance(e, HTTPError)
                        and e.response is not None
                        and self.retry_callback is not None
                    ):
                        self.retry_callback(e.response.status_code, e.response.text)
                    else:
                        # todo: would like to catch other errors, eg wandb.errors.Error, ConnectionError etc
                        # but some of these can be raised before the retry handler thread (RunStatusChecker) is
                        # spawned in wandb_init
                        wandb.termlog(
                            "{} ({}), entering retry loop.".format(
                                self._error_prefix, e.__class__.__name__
                            )
                        )
                # if wandb.env.is_debug():
                #     traceback.print_exc()
            self._sleep_fn(sleep + random.random() * 0.25 * sleep)
            sleep *= 2
            if sleep > self.MAX_SLEEP_SECONDS:
                sleep = self.MAX_SLEEP_SECONDS
            now = self._datetime_now_fn()

            self._num_iter += 1


_F = TypeVar("_F", bound=Callable)


def retriable(*args: Any, **kargs: Any) -> Callable[[_F], _F]:
    def decorator(fn: _F) -> _F:
        retrier: Retry[Any] = Retry(fn, *args, **kargs)

        @functools.wraps(fn)
        def wrapped_fn(*args: Any, **kargs: Any) -> Any:
            return retrier(*args, **kargs)

        return wrapped_fn  # type: ignore

    return decorator
