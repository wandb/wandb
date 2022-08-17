"""
mailbox.
"""

import secrets
import string
import threading
import time
from typing import Callable, Dict, Optional

from wandb.proto import wandb_internal_pb2 as pb


def _generate_address(length: int = 12) -> str:
    address = "".join(
        secrets.choice(string.ascii_lowercase + string.digits) for i in range(length)
    )
    return address


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
        with self._lock:
            if self._event.wait(timeout=timeout):
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

    def __init__(self, mailbox: "Mailbox", slot: _MailboxSlot) -> None:
        self._mailbox = mailbox
        self._slot = slot

    def wait(
        self,
        timeout: Optional[float] = None,
        on_progress: Callable[[MailboxProgressHandle], None] = None,
        release: bool = True,
    ) -> Optional[pb.Result]:
        found: Optional[pb.Result] = None
        start_time = time.time()
        percent_done = 0.0
        while True:
            found = self._slot._get_and_clear(timeout=1)
            if found:
                break
            now = time.time()
            if timeout is not None:
                if now >= start_time + timeout:
                    break
            if on_progress:
                if timeout:
                    percent_done = min((now - start_time) / timeout, 1.0)
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

    def __init__(self) -> None:
        self._slots = {}

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
