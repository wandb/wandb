"""Writer thread.

    States
    ------
    ACTIVE = Streaming every record to the sender
    PAUSED = Collecting requests to the current block
    RESTARTING = Transitionary state waiting for request
                 completing a block

    Examples
    --------
    |   Block1   |   Block2   |   Block3   |   Block4   |
    |      < 0><  1 ><-2-><--3-->          |            |

inmem col: 0        col 1,2       col 3


New messages:
  mark_position    writer -> sender (has an ID)
  report position  sender -> writer
  read data        writer -> sender (go read this data for me)

"""

import enum
import logging

from ..lib import tracelog
from . import datastore

logger = logging.getLogger(__name__)


class _SendState(enum.Enum):
    ACTIVE = 1
    PAUSED = 2
    RESTARTING = 3


class WriteManager:
    def __init__(
        self,
        settings,
        record_q,
        result_q,
        sender_q,
    ):
        self._settings = settings
        self._record_q = record_q
        self._result_q = result_q
        self._sender_q = sender_q
        self._ds = None

        # thresholds to define when to PAUSE and RESTART
        self._threshold_block_high = 20
        self._threshold_block_low = 4

        # collection of requests ending in current block
        self._collection_block = None
        self._collection_records = []

        # track last written request
        self._written_offset = None
        self._written_block_start = None
        self._written_block_end = None

        # state machine ACTIVE -> PAUSED -> RESTARTING -> ACTIVE ...
        self._state = _SendState.ACTIVE

    def open(self):
        self._ds = datastore.DataStore()
        self._ds.open_for_write(self._settings.sync_file)

    def _process_control_record(self, record) -> bool:
        record_type = record.WhichOneof("record_type")
        if record_type == "sender_update_seen":
            # sender_position_update (result from sender_position_req
            self._sender_position = None  # TODO
        elif record_type == "sender_update_read":
            pass
        return False

    def _process_report_sender_position(self):
        # request: inquiry
        # response: report
        # sender_position_inquiry
        # sender_position_report
        pass

    def _maybe_request_read(self):
        pass
        # if we are paused
        # and more than one chunk has been written
        # and N time has elapsed
        # send message asking sender to read from last_read_offset to current_offset

    def _write_record(self, record):
        is_control_record = self._process_control_record(record)
        if is_control_record:
            return

        ret = self._ds.write(record)
        assert ret is not None
        (file_offset, data_length, _, _) = ret

        self._written_offset = file_offset
        self._written_block_start = file_offset // datastore.LEVELDBLOG_BLOCK_LEN
        self._written_block_end = (
            file_offset + data_length
        ) // datastore.LEVELDBLOG_BLOCK_LEN

    def _send_record(self, record):
        tracelog.log_message_queue(record, self._sender_q)
        self._sender_q.put(record)

    def _collect_record(self, record):
        # move into send record
        # self._maybe_inquire_position()
        # if self._collection_blocknum != self._next_blocknum:
        #    self._collection_reset()
        pass

    def _blocks_behind(self) -> int:
        return 0

    def _maybe_pause(self):
        """Stop sending data to the sender if it is backed up."""
        if self._blocks_behind() < self._threshold_block_high:
            return
        self._state = _SendState.PAUSED

    def _maybe_restart(self):
        """Start looking for a good opportunity to actively use sender."""
        pass
        # self._mark_position()

    def _maybe_active(self):
        """Transition to the active state by sending collected records."""
        pass
        # if mark_position received
        #     send(collected records)

    def write(self, record):
        if not self._ds:
            self.open()

        self._write_record(record)

        # Transition sending state machine
        if self._state == _SendState.ACTIVE:
            self._maybe_pause()
        elif self._state == _SendState.PAUSED:
            self._maybe_restart()
        elif self._state == _SendState.RESTARTING:
            self._maybe_active()

        # Execute sending state machine actions
        if self._state == _SendState.ACTIVE:
            self._send_record(record)
        elif self._state == _SendState.PAUSED:
            self._collect_record(record)
        elif self.__state == _SendState.RESTARTING:
            self._collect_record(record)

    def finish(self):
        # TODO: send final read and collected records
        if self._ds:
            self._ds.close()

    def debounce(self) -> None:
        pass
