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

    def __call__(
        self,
        *args: Any,
        num_retries: Optional[int] = None,
        retry_timedelta: Optional[datetime.timedelta] = None,
        retry_sleep_base: Optional[float] = None,
        retry_cancel_event: Optional[threading.Event] = None,
        check_retry_fn: Optional[CheckRetryFnType] = None,
        **kwargs: Any,
    ) -> _R:
        """Call the wrapped function, with retries.

        Args:
            num_retries: The number of retries after which to give up.
            retry_timedelta: An amount of time after which to give up.
            retry_sleep_base: Number of seconds to sleep for the first retry.
                This is used as the base for exponential backoff.
            retry_cancel_event: An event that causes this to raise
                a RetryCancelledException on the next attempted retry.
            check_retry_fn: A custom check for deciding whether an exception
                should be retried. Retrying is prevented if this returns a falsy
                value, even if more retries are left. This may also return a
                timedelta that represents a shorter timeout: retrying is
                prevented if the value is less than the amount of time that has
                passed since the last timedelta was returned.
        """
        if os.environ.get("WANDB_TEST"):
            max_retries = 0
        elif num_retries is not None:
            max_retries = num_retries
        elif self._num_retries is not None:
            max_retries = self._num_retries
        else:
            max_retries = 1000000

        if retry_timedelta is not None:
            timeout = retry_timedelta
        elif self._retry_timedelta is not None:
            timeout = self._retry_timedelta
        else:
            timeout = datetime.timedelta(days=365)

        if retry_sleep_base is not None:
            initial_sleep = retry_sleep_base
        else:
            initial_sleep = 1

        retry_loop = _RetryLoop(
            max_retries=max_retries,
            timeout=timeout,
            initial_sleep=initial_sleep,
            max_sleep=self.MAX_SLEEP_SECONDS,
            cancel_event=retry_cancel_event or self._retry_cancel_event,
            retry_check=check_retry_fn or self._check_retry_fn,
        )

        start_time = NOW_FN()
        self._num_iter = 0

        while True:
            try:
                result = self._call_fn(*args, **kwargs)

            except self._retryable_exceptions as e:
                if not retry_loop.should_retry(e):
                    raise

                if self._num_iter == 2:
                    logger.info("Retry attempt failed:", exc_info=e)
                    self._print_entered_retry_loop(e)

                retry_loop.wait_before_retry()
                self._num_iter += 1

            else:
                if self._num_iter > 2:
                    self._print_recovered(start_time)

                return result

    def _print_entered_retry_loop(self, exception: Exception) -> None:
        """Emit a message saying we've begun retrying.

        Either calls the retry callback or prints a warning to console.

        Args:
            exception: The most recent exception we will retry.
        """
        if (
            isinstance(exception, HTTPError)
            and exception.response is not None
            and self.retry_callback is not None
        ):
            self.retry_callback(
                exception.response.status_code,
                exception.response.text,
            )
        else:
            wandb.termlog(
                f"{self._error_prefix}"
                f" ({exception.__class__.__name__}), entering retry loop."
            )

    def _print_recovered(self, start_time: datetime.datetime) -> None:
        """Emit a message saying we've recovered after retrying.

        Args:
            start_time: When we started retrying.
        """
        if not self.retry_callback:
            return

        now = NOW_FN()
        if now - self._last_print < datetime.timedelta(minutes=1):
            return
        self._last_print = now

        time_to_recover = now - start_time
        self.retry_callback(
            200,
            (
                f"{self._error_prefix} resolved after"
                f" {time_to_recover}, resuming normal operation."
            ),
        )


class _RetryLoop:
    """An invocation of a Retry instance."""

    def __init__(
        self,
        *,
        max_retries: int,
        timeout: datetime.timedelta,
        initial_sleep: float,
        max_sleep: float,
        cancel_event: Optional[threading.Event],
        retry_check: CheckRetryFnType,
    ) -> None:
        """Start a new call of a Retry instance.

        Args:
            max_retries: The number of retries after which to give up.
            timeout: An amount of time after which to give up.
            initial_sleep: Number of seconds to sleep for the first retry.
                This is used as the base for exponential backoff.
            max_sleep: Maximum number of seconds to sleep between retries.
            cancel_event: An event that's set when the function is cancelled.
            retry_check: A custom check for deciding whether an exception should
                be retried. Retrying is prevented if this returns a falsy value,
                even if more retries are left. This may also return a timedelta
                that represents a shorter timeout: retrying is prevented if the
                value is less than the amount of time that has passed since the
                last timedelta was returned.
        """
        self._max_retries = max_retries
        self._total_retries = 0

        self._timeout = timeout
        self._start_time = NOW_FN()

        self._next_sleep_time = initial_sleep
        self._max_sleep = max_sleep
        self._cancel_event = cancel_event

        self._retry_check = retry_check
        self._last_custom_timeout: Optional[datetime.datetime] = None

    def should_retry(self, exception: Exception) -> bool:
        """Returns whether an exception should be retried."""
        if self._total_retries >= self._max_retries:
            return False
        self._total_retries += 1

        now = NOW_FN()
        if now - self._start_time >= self._timeout:
            return False

        retry_check_result = self._retry_check(exception)
        if not retry_check_result:
            return False

        if isinstance(retry_check_result, datetime.timedelta):
            if not self._last_custom_timeout:
                self._last_custom_timeout = now

            if now - self._last_custom_timeout >= retry_check_result:
                return False

        return True

    def wait_before_retry(self) -> None:
        """Block until the next retry should happen.

        Raises:
            RetryCancelledError: If the operation is cancelled.
        """
        sleep_amount = self._next_sleep_time * (1 + random.random() * 0.25)

        if self._cancel_event:
            cancelled = self._cancel_event.wait(sleep_amount)
            if cancelled:
                raise RetryCancelledError("Cancelled while retrying.")
        else:
            SLEEP_FN(sleep_amount)

        self._next_sleep_time *= 2
        if self._next_sleep_time > self._max_sleep:
            self._next_sleep_time = self._max_sleep


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
