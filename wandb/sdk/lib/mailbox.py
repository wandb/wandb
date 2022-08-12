"""
intents.
"""

import threading
from typing import Dict, Optional

from wandb.proto import wandb_internal_pb2 as pb


class _Box:
    _result: Optional[pb.Result]
    _event: threading.Event

    def __init__(self) -> None:
        self._result = None
        self._event = threading.Event()


class Mailbox:
    _boxes: Dict[str, _Box]

    def __init__(self) -> None:
        self._boxes = {}

    def deliver(self, result: pb.Result) -> None:
        mailbox = result.mailbox
        self._boxes[mailbox]._result = result
        self._boxes[mailbox]._event.set()

    def allocate_box(self) -> str:
        address = "junk"
        self._boxes[address] = _Box()
        return address

    def release_box(self, address: str) -> None:
        pass

    def wait_box(
        self, address: str, timeout: Optional[float] = None
    ) -> Optional[pb.Result]:
        box = self._boxes.get(address)
        assert box
        found = box._event.wait(timeout=timeout)
        if found:
            return box._result
        return None
