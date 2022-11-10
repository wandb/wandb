"""Reader thread."""

import logging
from queue import Queue
from typing import TYPE_CHECKING, Callable

from .settings_static import SettingsStatic
from ..lib import tracelog

if TYPE_CHECKING:
    from wandb.proto.wandb_internal_pb2 import Record, Result

logger = logging.getLogger(__name__)


class ReadManager:
    def __init__(
        self,
        settings: SettingsStatic,
        record_q: "Queue[Record]",
        result_q: "Queue[Result]",
        writer_q: "Queue[Record]",
        sender_q: "Queue[Record]",
    ) -> None:
        self._settings = settings
        self._record_q = record_q
        self._result_q = result_q
        self._writer_q = writer_q
        self._sender_q = sender_q

    def send_record(self, record: "Record") -> None:
        tracelog.log_message_queue(record, self._sender_q)
        self._sender_q.put(record)

    def relay_to_writer(self, record: "Record") -> None:
        tracelog.log_message_queue(record, self._writer_q)
        self._writer_q.put(record)

    def relay_to_sender(self, record: "Record") -> None:
        tracelog.log_message_queue(record, self._sender_q)
        self._sender_q.put(record)

    def read_request_sender_mark(self, record: "Record") -> None:
        self.relay_to_sender(record)

    def read_request_sender_mark_report(self, record: "Record") -> None:
        self.relay_to_writer(record)

    def read_request_sender_read(self, record: "Record") -> None:
        pass

    def relay_record(self, record: "Record") -> None:
        self.relay_to_sender(record)

    def read_request(self, record: "Record") -> None:
        request_type = record.request.WhichOneof("request_type")
        assert request_type
        handler_str = "read_request_" + request_type
        read_handler: Callable[["Record"], None] = getattr(
            self, handler_str, self.relay_record
        )
        read_handler(record)

    def read(self, record: "Record") -> None:
        record_type = record.WhichOneof("record_type")
        assert record_type
        handler_str = "read_" + record_type
        read_handler: Callable[["Record"], None] = getattr(
            self, handler_str, self.relay_record
        )
        read_handler(record)

    def finish(self) -> None:
        pass

    def debounce(self) -> None:
        pass
