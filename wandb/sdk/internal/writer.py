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
    _flow_control: Optional[flow_control.Director]

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
        self._flow_control = flow_control.Director(
            settings=self._settings,
            write_record=self._write_record,
            forward_record=self._forward_record,
            ensure_flushed=self._ensure_flushed,
        )

    def _forward_record(self, record: "Record") -> None:
        tracelog.log_message_queue(record, self._sender_q)
        self._sender_q.put(record)

    def _write_record(self, record: "Record") -> flow_control._WriteInfo:
        ret = self._ds.write(record)
        assert ret is not None

        # (file_offset, data_length, _, _) = ret
        # self._last_block_end = self._written_block_end
        # self._written_offset = file_offset
        # self._written_block_start = file_offset // datastore.LEVELDBLOG_BLOCK_LEN
        # self._written_block_end = (
        #     file_offset + data_length
        # ) // datastore.LEVELDBLOG_BLOCK_LEN


    def _ensure_flushed(self, offset: int) -> None:
        pass

    def write(self, record: "Record") -> None:
        if not self._ds:
            self.open()
        assert self._flow_control

        # Director will write data to disk and throttle sending to the sender
        self._flow_control.direct(record)

    def finish(self) -> None:
        if self._ds:
            self._ds.close()
        if self._flow_control:
            self._flow_control.flush()

    def debounce(self) -> None:
        pass
