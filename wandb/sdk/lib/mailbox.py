"""
mailbox.
"""

import secrets
import string
import threading
import time
from typing import TYPE_CHECKING, Callable, Dict, List, Optional

from wandb.proto import wandb_internal_pb2 as pb

if TYPE_CHECKING:
    from wandb.sdk.interface.interface_shared import InterfaceShared


def _generate_address(length: int = 12) -> str:
    address = "".join(
        secrets.choice(string.ascii_lowercase + string.digits) for i in range(length)
    )
    return address


class MailboxError(Exception):
    """Generic Mailbox Exception"""

    pass


class _MailboxSlot:
    _result: Optional[pb.Result]
    _event: threading.Event
    _lock: threading.Lock
    _address: str

    def __init__(self, address: str) -> None:
        self._result = None
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._address = address

    def _get_and_clear(self, timeout: float) -> Optional[pb.Result]:
        found = None
        if self._event.wait(timeout=timeout):
            with self._lock:
                found = self._result
                self._event.clear()
        return found

    def _deliver(self, result: pb.Result) -> None:
        with self._lock:
            self._result = result
            self._event.set()


class MailboxProgressHandle:
    _percent_done: float

    def __init__(self, percent_done: float) -> None:
        self._percent_done = percent_done

    @property
    def percent_done(self) -> float:
        return self._percent_done


class MailboxHandle:
    _mailbox: "Mailbox"
    _slot: _MailboxSlot
    _on_progress: Optional[Callable[[MailboxProgressHandle], None]]
    _interface: Optional["InterfaceShared"]
    _keepalive: bool

    def __init__(self, mailbox: "Mailbox", slot: _MailboxSlot) -> None:
        self._mailbox = mailbox
        self._slot = slot
        self._on_progress = None
        self._interface = None
        self._keepalive = False
        self._keepalive_interval = 5

    def add_progress(
        self, on_progress: Callable[[MailboxProgressHandle], None]
    ) -> None:
        self._on_progress = on_progress

    def _transport_keepalive_failed(self) -> bool:
        if not self._interface:
            return False
        if not self._interface._transport_failed:
            now = time.time()
            if (
                now
                > self._interface._transport_success_timestamp
                + self._keepalive_interval
            ):
                try:
                    self._interface._publish_keepalive()
                except Exception:
                    self._interface._transport_mark_failed()
                else:
                    self._interface._transport_mark_success()
        return self._interface._transport_failed

    def wait(
        self,
        *,
        timeout: float,
        on_progress: Callable[[MailboxProgressHandle], None] = None,
        release: bool = True,
    ) -> Optional[pb.Result]:
        on_progress = on_progress or self._on_progress
        found: Optional[pb.Result] = None
        start_time = time.time()
        percent_done = 0.0
        progress_sent = False
        wait_timeout = 1.0
        if timeout >= 0:
            wait_timeout = min(timeout, wait_timeout)
        while True:
            if self._transport_keepalive_failed():
                raise MailboxError("transport failed")

            found = self._slot._get_and_clear(timeout=wait_timeout)
            if found:
                # Always update progress to 100% when done
                if on_progress and progress_sent:
                    progress = MailboxProgressHandle(percent_done=100)
                    on_progress(progress)
                break
            now = time.time()
            if timeout >= 0:
                if now >= start_time + timeout:
                    break
            if on_progress:
                if timeout > 0:
                    percent_done = min((now - start_time) / timeout, 1.0)
                progress_sent = True
                progress = MailboxProgressHandle(percent_done=percent_done)
                on_progress(progress)
        if release:
            self._release()
        return found

    def _release(self) -> None:
        self._mailbox._release_slot(self.address)

    @property
    def address(self) -> str:
        return self._slot._address


class Mailbox:
    _slots: Dict[str, _MailboxSlot]
    _keepalive: bool

    def __init__(self) -> None:
        self._slots = {}
        self._keepalive = False

    def enable_keepalive(self) -> None:
        self._keepalive = True

    def wait(
        self,
        handle: MailboxHandle,
        *,
        timeout: float,
        on_progress: Callable[[MailboxProgressHandle], None] = None,
    ) -> Optional[pb.Result]:
        return handle.wait(timeout=timeout, on_progress=on_progress)

    def wait_all(
        self,
        handles: List[MailboxHandle],
        *,
        timeout: float,
        on_progress: Callable[[MailboxProgressHandle], None] = None,
    ) -> None:
        for handle in handles:
            _ = handle.wait(timeout=-1)

    def deliver(self, result: pb.Result) -> None:
        mailbox = result.control.mailbox_slot
        slot = self._slots.get(mailbox)
        if not slot:
            return
        slot._deliver(result)

    def _allocate_slot(self) -> _MailboxSlot:
        address = _generate_address()
        slot = _MailboxSlot(address=address)
        self._slots[address] = slot
        return slot

    def _release_slot(self, address: str) -> None:
        self._slots.pop(address, None)

    def get_handle(self) -> MailboxHandle:
        slot = self._allocate_slot()
        handle = MailboxHandle(mailbox=self, slot=slot)
        return handle

    def _deliver_record(
        self, record: pb.Record, interface: "InterfaceShared"
    ) -> MailboxHandle:
        handle = self.get_handle()
        handle._interface = interface
        handle._keepalive = self._keepalive
        record.control.mailbox_slot = handle.address
        try:
            interface._publish(record)
        except Exception:
            interface._transport_mark_failed()
            raise
        interface._transport_mark_success()
        return handle
