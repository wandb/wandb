from __future__ import annotations

import logging
import secrets
import string
import threading

from wandb.proto import wandb_internal_pb2 as pb

from . import handles

_logger = logging.getLogger(__name__)


class Mailbox:
    """Matches service responses to requests.

    The mailbox can set an address on a Record and create a handle for
    waiting for a response to that record. Responses are delivered by calling
    `deliver()`. The `close()` method abandons all handles in case the
    service process becomes unreachable.
    """

    def __init__(self) -> None:
        self._handles: dict[str, handles.MailboxHandle] = {}
        self._handles_lock = threading.Lock()

    def require_response(self, request: pb.Record) -> handles.MailboxHandle:
        """Set a response address on a request.

        Args:
            request: The request on which to set a mailbox slot.
                This is mutated. An address must not already be set.

        Returns:
            A handle for waiting for the response to the request.
        """
        if address := request.control.mailbox_slot:
            raise ValueError(f"Request already has an address ({address})")

        address = self._new_address()
        request.control.mailbox_slot = address

        with self._handles_lock:
            handle = handles.MailboxHandle(address)
            self._handles[address] = handle

        return handle

    def _new_address(self) -> str:
        """Returns an unused address for a request.

        Assumes `_handles_lock` is held.
        """

        def generate():
            return "".join(
                secrets.choice(string.ascii_lowercase + string.digits)
                for i in range(12)
            )

        address = generate()

        # Being extra cautious. This loop will almost never be entered.
        while address in self._handles:
            address = generate()

        return address

    def deliver(self, result: pb.Result) -> None:
        """Deliver a response from the service.

        If the response address is invalid, this does nothing.
        """
        address = result.control.mailbox_slot
        if not address:
            _logger.error(
                "Received response with no mailbox slot."
                f" Kind: {result.WhichOneof('result_type')}"
            )
            return

        with self._handles_lock:
            handle = self._handles.pop(address, None)

        # It is not an error if there is no handle for the address:
        # handles can be abandoned if the result is no longer needed.
        if handle:
            handle.deliver(result)

    def close(self) -> None:
        """Indicate no further responses will be delivered.

        Abandons all handles.
        """
        with self._handles_lock:
            _logger.info(
                f"Closing mailbox, abandoning {len(self._handles)} handles.",
            )

            for handle in self._handles.values():
                handle.abandon()
            self._handles.clear()
