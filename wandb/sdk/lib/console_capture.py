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

import sys
import threading
from typing import IO, AnyStr, Callable, Protocol


class CannotCaptureConsoleError(Exception):
    """The module failed to patch stdout or stderr."""


class _WriteCallback(Protocol):
    """A callback that receives intercepted bytes or string data.

    This may be called from any thread, but is only called from one thread
    at a time.
    """

    def __call__(
        self,
        data: bytes | str,
        written: int,
        /,
    ) -> None:
        """Intercept data passed to `write()`.

        Args:
            data: The object passed to stderr's or stdout's `write()`.
            written: The number of bytes or characters written.
                This is the return value of `write()`.
        """


# A reentrant lock is used to catch callbacks that write to stderr/stdout.
_module_lock = threading.RLock()
_is_writing = False

_patch_exception: CannotCaptureConsoleError | None = None

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
    with _module_lock:
        if _patch_exception:
            raise _patch_exception

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
    with _module_lock:
        if _patch_exception:
            raise _patch_exception

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

            del callback_dict[id]

            disposed = True

    callback_dict[id] = callback
    return dispose


def _patch(
    stdout_or_stderr: IO[AnyStr],
    callbacks: dict[int, _WriteCallback],
) -> None:
    orig_write: Callable[[AnyStr], int]

    def write_with_callbacks(s: AnyStr, /) -> int:
        global _is_writing
        n = orig_write(s)

        # NOTE: Since _module_lock is reentrant, this is safe. It will not
        # deadlock if a callback invokes write() again.
        with _module_lock:
            if _is_writing:
                return n

            _is_writing = True
            try:
                for cb in callbacks.values():
                    cb(s, n)
            finally:
                _is_writing = False

        return n

    orig_write = stdout_or_stderr.write

    # mypy==1.14.1 fails to type-check this:
    #   Incompatible types in assignment (expression has type
    #   "Callable[[bytes], int]", variable has type overloaded function)
    stdout_or_stderr.write = write_with_callbacks  # type: ignore


try:
    _patch(sys.stdout, _stdout_callbacks)
    _patch(sys.stderr, _stderr_callbacks)
except Exception as _patch_exception_cause:
    _patch_exception = CannotCaptureConsoleError()
    _patch_exception.__cause__ = _patch_exception_cause
