"""Module for intercepting stdout/stderr.

This patches the `write()` method of `stdout` and `stderr` on import.
Once patched, it is not possible to unpatch or repatch, though individual
callbacks can be removed.

We assume that all other writing methods on the object delegate to `write()`,
like `writelines()`. This is not guaranteed to be true, but it is true for
common implementations. In particular, CPython's implementation of IOBase's
`writelines()` delegates to `write()`.

It is important to note that this technique interacts poorly with other
code that performs similar patching if it also allows unpatching as this
discards our modification. This is why we patch on import and do not support
unpatching:

    with contextlib.redirect_stderr(...):
        from ... import console_capture
        # Here, everything works fine.
    # Here, callbacks are never called again.

In particular, it does not work with some combinations of pytest's
`capfd` / `capsys` fixtures and pytest's `--capture` option.
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
import sys
import threading
from typing import IO, AnyStr, Callable, Iterator, Protocol

from . import wb_logging

_logger = logging.getLogger(__name__)


class CannotCaptureConsoleError(Exception):
    """The module failed to patch stdout or stderr."""


class _WriteCallback(Protocol):
    """A callback that receives intercepted bytes or string data.

    This may be called from any thread, but is only called from one thread
    at a time.

    Note on errors: Any error raised during the callback will clear all
    callbacks. This means that if a user presses Ctrl-C at an unlucky time
    during a run, we will stop uploading console output---but it's not
    likely to be a problem unless something catches the KeyboardInterrupt.

    Regular Exceptions are caught and logged instead of bubbling up to the
    user's print() statements; other exceptions like KeyboardInterrupt are
    re-raised.

    Callbacks should handle all exceptions---a callback that raises any
    Exception is considered buggy.
    """

    def __call__(
        self,
        data: bytes | str,
        written: int,
        /,
    ) -> None:
        """Intercept data passed to `write()`.

        See the protocol docstring for information about exceptions.

        Args:
            data: The object passed to stderr's or stdout's `write()`.
            written: The number of bytes or characters written.
                This is the return value of `write()`.
        """


_module_lock = threading.Lock()

# See _enter_callbacks().
_is_writing = False
_is_caused_by_callback = contextvars.ContextVar(
    "_is_caused_by_callback",
    default=False,
)

_patch_exception: CannotCaptureConsoleError | None = None


def _maybe_raise_patch_exception() -> None:
    """Raise _patch_exception if it's set."""
    if _patch_exception:
        # Each `raise` call modifies the exception's __traceback__, so we must
        # reset the traceback to reuse the exception.
        #
        # See https://bugs.python.org/issue45924 for an example of the problem.
        raise _patch_exception.with_traceback(None)


_next_callback_id: int = 1

_stdout_callbacks: dict[int, _WriteCallback] = {}
_stderr_callbacks: dict[int, _WriteCallback] = {}


def capture_stdout(callback: _WriteCallback) -> Callable[[], None]:
    """Install a callback that runs after every write to sys.stdout.

    Args:
        callback: A callback to invoke after running `sys.stdout.write`.

    Returns:
        A function to uninstall the callback.

    Raises:
        CannotCaptureConsoleError: If patching failed on import.
    """
    _maybe_raise_patch_exception()

    with _module_lock:
        return _insert_disposably(
            _stdout_callbacks,
            callback,
        )


def capture_stderr(callback: _WriteCallback) -> Callable[[], None]:
    """Install a callback that runs after every write to sys.sdterr.

    Args:
        callback: A callback to invoke after running `sys.stderr.write`.

    Returns:
        A function to uninstall the callback.

    Raises:
        CannotCaptureConsoleError: If patching failed on import.
    """
    _maybe_raise_patch_exception()

    with _module_lock:
        return _insert_disposably(
            _stderr_callbacks,
            callback,
        )


def _insert_disposably(
    callback_dict: dict[int, _WriteCallback],
    callback: _WriteCallback,
) -> Callable[[], None]:
    global _next_callback_id
    id = _next_callback_id
    _next_callback_id += 1

    disposed = False

    def dispose() -> None:
        nonlocal disposed

        with _module_lock:
            if disposed:
                return

            callback_dict.pop(id, None)

            disposed = True

    callback_dict[id] = callback
    return dispose


def _patch(
    stdout_or_stderr: IO[AnyStr],
    callbacks: dict[int, _WriteCallback],
) -> None:
    orig_write: Callable[[AnyStr], int]

    def write_with_callbacks(s: AnyStr, /) -> int:
        n = orig_write(s)

        with contextlib.ExitStack() as stack:
            stack.enter_context(_reset_on_exception())
            stack.enter_context(wb_logging.log_to_all_runs())
            callbacks_list = stack.enter_context(_enter_callbacks(callbacks))

            for cb in callbacks_list:
                cb(s, n)

        return n

    orig_write = stdout_or_stderr.write

    # mypy==1.14.1 fails to type-check this:
    #   Incompatible types in assignment (expression has type
    #   "Callable[[bytes], int]", variable has type overloaded function)
    stdout_or_stderr.write = write_with_callbacks  # type: ignore


@contextlib.contextmanager
def _enter_callbacks(
    callbacks: dict[int, _WriteCallback],
) -> Iterator[list[_WriteCallback]]:
    """Returns a list of callbacks to invoke.

    This prevents deadlocks and some infinite loops by returning an empty list
    when:

    * A callback prints
    * A callback blocks on a thread that's printing
    * A callback schedules an async task that prints

    It is impossible to prevent all infinite loops: a callback could put
    a message into a queue, causing an unrelated thread to print later,
    invoking the same callback and repeating forever.
    """
    global _is_writing

    # The global _is_writing variable is necessary despite the contextvar
    # because it's possible to create a thread without copying the context.
    # This is the default behavior for threading.Thread() before Python 3.14.
    #
    # A side effect of it is that when multiple threads print simultaneously,
    # some messages will not be captured.

    with _module_lock:
        if _is_writing or _is_caused_by_callback.get():
            callbacks_list = None

        else:
            callbacks_list = list(callbacks.values())
            _is_writing = True
            _is_caused_by_callback.set(True)

    if callbacks_list is None:
        yield []
        return

    try:
        yield callbacks_list
    finally:
        with _module_lock:
            _is_writing = False
            _is_caused_by_callback.set(False)


@contextlib.contextmanager
def _reset_on_exception() -> Iterator[None]:
    """Clear all callbacks on any exception, suppressing it.

    This prevents infinite loops:

    * If we re-raise, an exception handler is likely to print
      the exception to the console and trigger callbacks again
    * If we log, we can't guarantee that this doesn't print
      to console.

    This is especially important for KeyboardInterrupt.
    """
    try:
        yield
    except BaseException as e:
        with _module_lock:
            _stderr_callbacks.clear()
            _stdout_callbacks.clear()

        if isinstance(e, Exception):
            # We suppress Exceptions so that bugs in W&B code don't
            # cause the user's print() statements to raise errors.
            _logger.exception("Error in console callback, clearing all!")
        else:
            # Re-raise errors like KeyboardInterrupt.
            raise


try:
    _patch(sys.stdout, _stdout_callbacks)
    _patch(sys.stderr, _stderr_callbacks)
except Exception as _patch_exception_cause:
    _patch_exception = CannotCaptureConsoleError()
    _patch_exception.__cause__ = _patch_exception_cause
