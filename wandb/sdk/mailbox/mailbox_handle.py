from __future__ import annotations

import abc
from typing import TYPE_CHECKING, Callable, Generic

from typing_extensions import TypeVar, override

from wandb.sdk.lib import asyncio_manager

# Necessary to break an import loop.
if TYPE_CHECKING:
    from wandb.sdk.interface import interface


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
    def abandon(self) -> None:
        """Abandon the handle, indicating it will not receive a response.

        This may not happen immediately: it is possible for an existing
        call to `wait_async` to complete successfully after this method returns.
        """

    @abc.abstractmethod
    def cancel(self, iface: interface.InterfaceBase) -> None:
        """Cancel the handle, requesting any associated work to not complete.

        It is an error to call this from an async function.

        This automatically abandons the handle, as a response is no longer
        guaranteed.

        Args:
            iface: The interface on which to publish the cancel request.
        """

    @abc.abstractmethod
    def wait_or(self, *, timeout: float | None) -> _T:
        """Wait for a response or a timeout.

        It is an error to call this from an async function.

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
    def abandon(self) -> None:
        self._handle.abandon()

    @override
    def cancel(self, iface: interface.InterfaceBase) -> None:
        self._handle.cancel(iface)

    @override
    def wait_or(self, *, timeout: float | None) -> _S:
        return self._fn(self._handle.wait_or(timeout=timeout))

    @override
    async def wait_async(self, *, timeout: float | None) -> _S:
        response = await self._handle.wait_async(timeout=timeout)
        return self._fn(response)
