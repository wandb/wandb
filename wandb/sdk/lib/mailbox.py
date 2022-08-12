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
    _mailbox: "Mailbox"
    _result: Optional[pb.Result]
    _event: threading.Event
    _address: str

    def __init__(self, mailbox: "Mailbox", address: str) -> None:
        self._mailbox = mailbox
        self._address = address
        self._result = None
        self._event = threading.Event()

    def wait(
        self, timeout: Optional[float] = None, on_progress: Callable[[], None] = None
    ) -> Optional[pb.Result]:

        start_time = time.time()
        while True:
            if self._event.wait(timeout=1):
                self.release()
                return self._result
            if timeout is not None:
                now = time.time()
                if now > start_time + timeout:
                    break
            if on_progress:
                on_progress()
        self.release()
        return None

    def release(self) -> None:
        self._mailbox.release_slot(self._address)


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
        self._slots.pop(address, None)
