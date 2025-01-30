import abc
import asyncio
import datetime
import functools
import logging
import os
import random
import threading
import time
from typing import Any, Awaitable, Callable, Generic, Optional, Tuple, Type, TypeVar

from requests import HTTPError

import wandb
import wandb.errors
from wandb.util import CheckRetryFnType

logger = logging.getLogger(__name__)


# To let tests mock out the retry logic's now()/sleep() funcs, this file
# should only use these variables, not call the stdlib funcs directly.
NOW_FN = datetime.datetime.now
SLEEP_FN = time.sleep
SLEEP_ASYNC_FN = asyncio.sleep


class RetryCancelledError(wandb.errors.Error):
    """A retry did not occur because it was cancelled."""


class TransientError(Exception):
    """Exception type designated for errors that may only be temporary.

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
    """Create a retryable version of a function.

    Calling this will call the passed function, retrying if any exceptions in
    retryable_exceptions are caught, with exponential backoff.
    """

    MAX_SLEEP_SECONDS = 5 * 60

    def __init__(
        self,
        call_fn: Callable[..., _R],
        retry_timedelta: Optional[datetime.timedelta] = None,
        retry_cancel_event: Optional[threading.Event] = None,
        num_retries: Optional[int] = None,
        check_retry_fn: CheckRetryFnType = lambda e: True,
        retryable_exceptions: Optional[Tuple[Type[Exception], ...]] = None,
        error_prefix: str = "Network error",
        retry_callback: Optional[Callable[[int, str], Any]] = None,
    ) -> None:
        self._call_fn = call_fn
        self._check_retry_fn = check_retry_fn
        self._error_prefix = error_prefix
        self._last_print = datetime.datetime.now() - datetime.timedelta(minutes=1)
        self._retry_timedelta = retry_timedelta
        self._retry_cancel_event = retry_cancel_event
        self._num_retries = num_retries
        if retryable_exceptions is not None:
            self._retryable_exceptions = retryable_exceptions
        else:
            self._retryable_exceptions = (TransientError,)
        self._index = 0
        self.retry_callback = retry_callback

    def _sleep_check_cancelled(
        self, wait_seconds: float, cancel_event: Optional[threading.Event]
    ) -> bool:
        if not cancel_event:
            SLEEP_FN(wait_seconds)
            return False
        cancelled = cancel_event.wait(wait_seconds)
        return cancelled

    @property
    def num_iters(self) -> int:
        """The number of iterations the previous __call__ retried."""
        return self._num_iter

    def __call__(self, *args: Any, **kwargs: Any) -> _R:  # noqa: C901
        """Call the wrapped function, with retries.

        Args:
           retry_timedelta (kwarg): amount of time to retry before giving up.
           sleep_base (kwarg): amount of time to sleep upon first failure, all other sleeps
               are derived from this one.
        """
        retry_timedelta = kwargs.pop("retry_timedelta", self._retry_timedelta)
        if retry_timedelta is None:
            retry_timedelta = datetime.timedelta(days=365)

        retry_cancel_event = kwargs.pop("retry_cancel_event", self._retry_cancel_event)

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
        now = NOW_FN()
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
                    self._last_print = NOW_FN()
                    if self.retry_callback:
                        self.retry_callback(
                            200,
                            "{} resolved after {}, resuming normal operation.".format(
                                self._error_prefix, NOW_FN() - start_time
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

                now = NOW_FN()

                # handle a triggered secondary check which could have a shortened timeout
                if isinstance(retry_timedelta_triggered, datetime.timedelta):
                    # save the time of the first secondary trigger
                    if not start_time_triggered:
                        start_time_triggered = now

                    # make sure that we haven't run out of time from secondary trigger
                    if now - start_time_triggered >= retry_timedelta_triggered:
                        raise

                # always enforce the default timeout from start of retries
                if now - start_time >= retry_timedelta:
                    raise

                if self._num_iter == 2:
                    logger.info("Retry attempt failed:", exc_info=e)
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
            cancelled = self._sleep_check_cancelled(
                sleep + random.random() * 0.25 * sleep, cancel_event=retry_cancel_event
            )
            if cancelled:
                raise RetryCancelledError("retry timeout")
            sleep *= 2
            if sleep > self.MAX_SLEEP_SECONDS:
                sleep = self.MAX_SLEEP_SECONDS
            now = NOW_FN()

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


class Backoff(abc.ABC):
    """A backoff strategy: decides whether to sleep or give up when an exception is raised."""

    @abc.abstractmethod
    def next_sleep_or_reraise(self, exc: Exception) -> datetime.timedelta:
        raise NotImplementedError  # pragma: no cover


class ExponentialBackoff(Backoff):
    """Jittered exponential backoff: sleep times increase ~exponentially up to some limit."""

    def __init__(
        self,
        initial_sleep: datetime.timedelta,
        max_sleep: datetime.timedelta,
        max_retries: Optional[int] = None,
        timeout_at: Optional[datetime.datetime] = None,
    ) -> None:
        self._next_sleep = min(max_sleep, initial_sleep)
        self._max_sleep = max_sleep
        self._remaining_retries = max_retries
        self._timeout_at = timeout_at

    def next_sleep_or_reraise(self, exc: Exception) -> datetime.timedelta:
        if self._remaining_retries is not None:
            if self._remaining_retries <= 0:
                raise exc
            self._remaining_retries -= 1

        if self._timeout_at is not None and NOW_FN() > self._timeout_at:
            raise exc

        result, self._next_sleep = (
            self._next_sleep,
            min(self._max_sleep, self._next_sleep * (1 + random.random())),
        )

        return result


class FilteredBackoff(Backoff):
    """Re-raise any exceptions that fail a predicate; delegate others to another Backoff."""

    def __init__(self, filter: Callable[[Exception], bool], wrapped: Backoff) -> None:
        self._filter = filter
        self._wrapped = wrapped

    def next_sleep_or_reraise(self, exc: Exception) -> datetime.timedelta:
        if not self._filter(exc):
            raise exc
        return self._wrapped.next_sleep_or_reraise(exc)


async def retry_async(
    backoff: Backoff,
    fn: Callable[..., Awaitable[_R]],
    *args: Any,
    on_exc: Optional[Callable[[Exception], None]] = None,
    **kwargs: Any,
) -> _R:
    """Call `fn` repeatedly until either it succeeds, or `backoff` decides we should give up.

    Each time `fn` fails, `on_exc` is called with the exception.
    """
    while True:
        try:
            return await fn(*args, **kwargs)
        except Exception as e:
            if on_exc is not None:
                on_exc(e)
            await SLEEP_ASYNC_FN(backoff.next_sleep_or_reraise(e).total_seconds())
