from __future__ import annotations

import abc
from typing import Callable, Generic

from typing_extensions import TypeVar, override

from wandb.sdk.lib import asyncio_manager

_T = TypeVar("_T")
_S = TypeVar("_S")


class HandleAbandonedError(Exception):
    """The handle has no response and has been abandoned."""


class MailboxHandle(abc.ABC, Generic[_T]):
    """A handle for waiting on a response to a request."""

    def __init__(self, asyncer: asyncio_manager.AsyncioManager) -> None:
        self._asyncer = asyncer

    @property
    def asyncer(self) -> asyncio_manager.AsyncioManager:
        """The asyncio thread to which the handle belongs.

        The handle's async methods must be run using this object.
        """
        return self._asyncer

    def map(self, fn: Callable[[_T], _S]) -> MailboxHandle[_S]:
        """Returns a transformed handle.

        Methods on the returned handle call methods on this handle, but the
        response type is derived using the given function.

        Args:
            fn: A function to apply to this handle's result to get the new
                handle's result. The function should be pure and fast.
        """
        return _MailboxMappedHandle(self, fn)

    @abc.abstractmethod
    def cancel(self) -> None:
        """Cancel the handle, requesting any associated work to not complete.

        Any calls to `wait_or` or `wait_async` will raise `HandleAbandonedError`
        if they aren't resolved within a short time.

        Cancellation is best-effort. Most exceptions are logged and suppressed.
        """

    @abc.abstractmethod
    def wait_or(self, *, timeout: float | None) -> _T:
        """Wait for a response or a timeout.

        It is an error to call this from an async function.
        On error, including KeyboardInterrupt or a timeout,
        the handle cancels itself.

        Args:
            timeout: A finite number of seconds or None to never time out.
                If less than or equal to zero, times out immediately unless
                the response is available.

        Returns:
            The response if it arrives before the timeout or has already arrived.

        Raises:
            TimeoutError: If the timeout is reached.
            HandleAbandonedError: If the handle becomes abandoned.
        """

    @abc.abstractmethod
    async def wait_async(self, *, timeout: float | None) -> _T:
        """Wait for a response or timeout.

        This must run in an `asyncio` event loop.
        On error, including asyncio cancellation, KeyboardInterrupt or
        a timeout, the handle cancels itself.

        Args:
            timeout: A finite number of seconds or None to never time out.

        Returns:
            The response if it arrives before the timeout or has already arrived.

        Raises:
            TimeoutError: If the timeout is reached.
            HandleAbandonedError: If the handle becomes abandoned.
        """


class _MailboxMappedHandle(Generic[_S], MailboxHandle[_S]):
    """A mailbox handle whose result is derived from another handle."""

    def __init__(
        self,
        handle: MailboxHandle[_T],
        fn: Callable[[_T], _S],
    ) -> None:
        super().__init__(handle.asyncer)
        self._handle = handle
        self._fn = fn

    @override
    def cancel(self) -> None:
        self._handle.cancel()

    @override
    def wait_or(self, *, timeout: float | None) -> _S:
        return self._fn(self._handle.wait_or(timeout=timeout))

    @override
    async def wait_async(self, *, timeout: float | None) -> _S:
        response = await self._handle.wait_async(timeout=timeout)
        return self._fn(response)
