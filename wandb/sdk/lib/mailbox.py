"""
mailbox.
"""

import threading
import time
from typing import Callable, Dict, Optional

from wandb.proto import wandb_internal_pb2 as pb


class MailboxSlot:
    _result: Optional[pb.Result]
    _event: threading.Event
    _address: str

    def __init__(self, address: str) -> None:
        self._address = address
        self._result = None
        self._event = threading.Event()

    def wait(
        self, timeout: Optional[float] = None, on_progress: Callable[[], None] = None
    ) -> Optional[pb.Result]:

        start_time = time.time()
        while True:
            if self._event.wait(timeout=1):
                return self._result
            if timeout is not None:
                now = time.time()
                if now > start_time + timeout:
                    break
            if on_progress:
                on_progress()
        return None


class Mailbox:
    _slots: Dict[str, MailboxSlot]

    def __init__(self) -> None:
        self._slots = {}

    def deliver(self, result: pb.Result) -> None:
        mailbox = result.control.mailbox_slot
        self._slots[mailbox]._result = result
        self._slots[mailbox]._event.set()

    def allocate_slot(self) -> MailboxSlot:
        address = "junk"
        slot = MailboxSlot(address=address)
        self._slots[address] = slot
        return slot

    def release_box(self, address: str) -> None:
        pass

    def wait_box(
        self, address: str, timeout: Optional[float] = None
    ) -> Optional[pb.Result]:
        box = self._slots.get(address)
        assert box
        found = box._event.wait(timeout=timeout)
        if found:
            return box._result
        return None
