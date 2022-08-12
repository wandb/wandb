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


class MailboxSlot:
    _mailbox: Optional["Mailbox"]
    _result: Optional[pb.Result]
    _event: threading.Event
    _address: str

    def __init__(self, mailbox: "Mailbox", address: str) -> None:
        self._mailbox = mailbox
        self._address = address
        self._result = None
        self._event = threading.Event()

    def wait(
        self,
        timeout: Optional[float] = None,
        on_progress: Callable[[], None] = None,
        release: bool = True,
    ) -> Optional[pb.Result]:
        found: Optional[pb.Result] = None
        start_time = time.time()
        while True:
            if self._event.wait(timeout=1):
                found = self._result
                break
            if timeout is not None:
                now = time.time()
                if now > start_time + timeout:
                    break
            if on_progress:
                on_progress()
        if release:
            self.release()
        return found

    def release(self) -> None:
        if self._mailbox:
            self._mailbox.release_slot(self._address)

    def _forget(self) -> None:
        # remove circular reference so child slot can be gc'ed
        self._mailbox = None


class Mailbox:
    _slots: Dict[str, MailboxSlot]

    def __init__(self) -> None:
        self._slots = {}

    def deliver(self, result: pb.Result) -> None:
        mailbox = result.control.mailbox_slot
        slot = self._slots.get(mailbox)
        if not slot:
            return
        slot._result = result
        slot._event.set()

    def allocate_slot(self) -> MailboxSlot:
        address = _generate_address()
        slot = MailboxSlot(mailbox=self, address=address)
        self._slots[address] = slot
        return slot

    def release_slot(self, address: str) -> None:
        found = self._slots.pop(address, None)
        if found:
            found._forget()
