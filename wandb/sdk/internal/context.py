"""Context Keeper."""

import threading
from typing import Dict, Optional

from wandb.proto.wandb_internal_pb2 import Record, Result


class Context:
    _cancel_event: threading.Event

    def __init__(self) -> None:
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    @property
    def cancel_event(self) -> threading.Event:
        return self._cancel_event


def context_id_from_record(record: Record) -> str:
    context_id = record.control.mailbox_slot
    return context_id


def context_id_from_result(result: Result) -> str:
    context_id = result.control.mailbox_slot
    return context_id


class ContextKeeper:
    _active_items: Dict[str, Context]

    def __init__(self) -> None:
        self._active_items = {}

    def add(self, context_id: str) -> None:
        self._active_items[context_id] = Context()

    def get(self, context_id: str) -> Optional[Context]:
        item = self._active_items.get(context_id)
        return item

    def release(self, context_id: str) -> None:
        pass

    def cancel(self, context_id: str) -> None:
        item = self.get(context_id)
        if item:
            item.cancel()
