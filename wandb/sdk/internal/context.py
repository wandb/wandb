"""Context Manager."""

import threading
from typing import Dict, Optional

from wandb.proto.wandb_internal_pb2 import Record, Result


class Context:
    _cancel_event: threading.Event

    def __init__(self) -> None:
        self._cancel_event = threading.Event()

    @property
    def cancel_event(self) -> threading.Event:
        return self._cancel_event


class ContextManager:
    _active_items: Dict[str, Context]

    def __init__(self) -> None:
        self._active_items = {}

    def add_context_from_record(self, record: Record) -> None:
        mailbox_slot = record.control.mailbox_slot
        self._active_items[mailbox_slot] = Context()

    def get_context_from_record(self, record: Record) -> Optional[Context]:
        mailbox_slot = record.control.mailbox_slot
        item = self._active_items.get(mailbox_slot)
        return item

    def release_context_from_result(self, result: Result) -> None:
        pass

    def process_cancel_record(self, cancel_record: Record) -> None:
        cancel_slot = cancel_record.request.cancel.cancel_slot
        item = self._active_items.get(cancel_slot)
        if item:
            item._cancel_event.set()
