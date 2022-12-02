import datetime
import functools
import logging
import os
import random
import time
from typing import (
    Any,
    Callable,
    Generic,
    MutableMapping,
    Optional,
    Tuple,
    Type,
    TypeVar,
)

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

MAX_SLEEP_SECONDS = 5 * 60


class RetryChecker:
    def __init__(
        self,
        max_time: datetime.timedelta,
        max_retries: int,
        sleep_base: float,
        check_retry_fn: CheckRetryFnType,
    ):
        self._max_time = max_time
        self._max_retries = max_retries
        self._check_retry_fn = check_retry_fn

        self._next_sleep = sleep_base
        self._num_failures = 0
        self._start_time: Optional[datetime.datetime] = None
        self._start_time_triggered: Optional[datetime.datetime] = None

    @classmethod
    def clone_pop_override(
        cls,
        base: "RetryChecker",
        kwargs: MutableMapping[str, Any],
    ) -> "RetryChecker":

        retry_timedelta = kwargs.pop("retry_timedelta", base._max_time)
        if retry_timedelta is None:
            retry_timedelta = datetime.timedelta(days=365)

        num_retries = kwargs.pop("num_retries", base._max_retries)
        if num_retries is None:
            num_retries = 1000000

        if os.environ.get("WANDB_TEST"):
            num_retries = 0

        sleep_base: float = kwargs.pop("retry_sleep_base", 1)

        # an extra function to allow performing more logic on the filtered exception
        check_retry_fn: CheckRetryFnType = kwargs.pop(
            "check_retry_fn", base._check_retry_fn
        )

        return cls(
            max_time=retry_timedelta,
            max_retries=num_retries,
            sleep_base=sleep_base,
            check_retry_fn=check_retry_fn,
        )

    def next_retry_delay(self, e: Exception, now: datetime.datetime) -> Optional[float]:
        if self._start_time is None:
            self._start_time = now

        # if the secondary check fails, re-raise
        retry_timedelta_triggered = self._check_retry_fn(e)
        if not retry_timedelta_triggered:
            return None

        # always enforce num_retries no matter which type of exception was seen
        if self._num_failures >= self._max_retries:
            return None
        self._num_failures += 1

        # handle a triggered secondary check which could have a shortened timeout
        if isinstance(retry_timedelta_triggered, datetime.timedelta):
            # save the time of the first secondary trigger
            if self._start_time_triggered is None:
                self._start_time_triggered = now

            # make sure that we havent run out of time from secondary trigger
            if now - self._start_time_triggered >= retry_timedelta_triggered:
                return None

        # always enforce the default timeout from start of retries
        if now - self._start_time >= self._max_time:
            return None

        to_sleep = self._next_sleep * (1 + random.random() * 0.25)
        self._next_sleep = min(2 * self._next_sleep, MAX_SLEEP_SECONDS)

        return to_sleep


class RetryLogger:
    def __init__(
        self,
        error_prefix: str,
        retry_callback: Optional[Callable[[Exception], None]] = None,
    ):
        self._error_prefix = error_prefix
        self._retry_callback = retry_callback
        self._num_failures = 0
        self._logged_retry_loop_start = False

    def on_failure(self, e: Exception, now: datetime.datetime) -> None:
        self._num_failures += 1
        if self._num_failures == 2:
            logger.exception("Retry attempt failed:")
            if (
                isinstance(e, HTTPError)
                and e.response is not None
                and self._retry_callback is not None
            ):
                self._retry_callback(e.response.status_code, e.response.text)
            else:
                # todo: would like to catch other errors, eg wandb.errors.Error, ConnectionError etc
                # but some of these can be raised before the retry handler thread (RunStatusChecker) is
                # spawned in wandb_init
                wandb.termlog(
                    "{} ({}), entering retry loop.".format(
                        self._error_prefix, e.__class__.__name__
                    )
                )
            self._logged_retry_loop_start = True

    def on_success(self) -> None:
        if (
            self._retry_callback is not None
            and self._logged_retry_loop_start
        ):
            self._retry_callback(
                200,
                "{} resolved after {}, resuming normal operation.".format(
                    self._error_prefix, self._datetime_now_fn() - self._start_time
                ),
            )


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
        self._base_retry_checker = RetryChecker(
            max_time=retry_timedelta
            if retry_timedelta is not None
            else datetime.timedelta(days=365),
            max_retries=num_retries if num_retries is not None else 1000000,
            sleep_base=1,
            check_retry_fn=check_retry_fn,
        )
        self._retry_callback = retry_callback
        self._error_prefix = error_prefix
        if retryable_exceptions is not None:
            self._retryable_exceptions = retryable_exceptions
        else:
            self._retryable_exceptions = (TransientError,)
        self._sleep_fn = sleep_fn_for_testing
        self._datetime_now_fn = datetime_now_fn_for_testing

    def __call__(self, *args: Any, **kwargs: Any) -> _R:
        """Call the wrapped function, with retries.

        Arguments:
           retry_timedelta (kwarg): amount of time to retry before giving up.
           sleep_base (kwarg): amount of time to sleep upon first failure, all other sleeps
               are derived from this one.
        """

        checker = RetryChecker.clone_pop_override(self._base_retry_checker, kwargs)
        logger = RetryLogger(
            error_prefix=self._error_prefix,
            retry_callback=self._retry_callback,
        )

        while True:
            try:
                result = self._call_fn(*args, **kwargs)
                logger.on_success()
                return result
            except self._retryable_exceptions as e:
                next_sleep = checker.next_retry_delay(
                    e=e, now=self._datetime_now_fn()
                )
                if next_sleep is None:
                    raise

                logger.on_failure(e=e, now=self._datetime_now_fn())
                self._sleep_fn(next_sleep)


_F = TypeVar("_F", bound=Callable)


def retriable(*args: Any, **kargs: Any) -> Callable[[_F], _F]:
    def decorator(fn: _F) -> _F:
        retrier: Retry[Any] = Retry(fn, *args, **kargs)

        @functools.wraps(fn)
        def wrapped_fn(*args: Any, **kargs: Any) -> Any:
            return retrier(*args, **kargs)

        return wrapped_fn  # type: ignore

    return decorator
