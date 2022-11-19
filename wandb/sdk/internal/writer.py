"""Writer thread."""

import logging
from typing import TYPE_CHECKING, Optional

from ..lib import tracelog
from . import datastore, flow_control
from .settings_static import SettingsStatic

if TYPE_CHECKING:
    from queue import Queue

    from wandb.proto.wandb_internal_pb2 import Record, Result


logger = logging.getLogger(__name__)


class WriteManager:
    _settings: SettingsStatic
    _record_q: "Queue[Record]"
    _result_q: "Queue[Result]"
    _sender_q: "Queue[Record]"
    _ds: Optional[datastore.DataStore]
    _flow_control: Optional[flow_control.FlowControl]

    def __init__(
        self,
        settings: SettingsStatic,
        record_q: "Queue[Record]",
        result_q: "Queue[Result]",
        sender_q: "Queue[Record]",
    ):
        self._settings = settings
        self._record_q = record_q
        self._result_q = result_q
        self._sender_q = sender_q
        self._ds = None
        self._flow_control = None

    def open(self) -> None:
        self._ds = datastore.DataStore()
        self._ds.open_for_write(self._settings.sync_file)
        self._flow_control = flow_control.FlowControl(
            settings=self._settings,
            write_record=self._write_record,
            forward_record=self._forward_record,
            ensure_flushed=self._ensure_flushed,
            # _threshold_bytes_high=1000,
            # _threshold_bytes_mid=500,
            # _threshold_bytes_low=200,
            # _mark_granularity_bytes=100,
            # _recovering_bytes_min=300,
        )

    def _forward_record(self, record: "Record") -> None:
        tracelog.log_message_queue(record, self._sender_q)
        self._sender_q.put(record)

    def _write_record(self, record: "Record") -> int:
        assert self._ds
        ret = self._ds.write(record)
        assert ret is not None

        (_start_offset, end_offset, flush_offset) = ret
        return end_offset

    def _ensure_flushed(self, offset: int) -> None:
        if self._ds:
            self._ds.ensure_flushed(offset)

    def write(self, record: "Record") -> None:
        if not self._ds:
            self.open()
        assert self._flow_control

        # temporarily support flow control being disabled (at first by default)
        if not self._settings._flow_control:
            self._write_record(record)
            self._forward_record(record)
            return

        # FlowControl will write data to disk and throttle sending to the sender
        self._flow_control.send_with_flow_control(record)

    def finish(self) -> None:
        if self._ds:
            self._ds.close()
        if self._flow_control:
            self._flow_control.flush()

    def debounce(self) -> None:
        pass
