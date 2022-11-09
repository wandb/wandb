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

from wandb.proto import wandb_internal_pb2 as pb

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
        self._written_block_start = 0
        self._written_block_end = 0

        # state machine ACTIVE -> PAUSED -> RESTARTING -> ACTIVE ...
        self._state = _SendState.ACTIVE

    def open(self):
        self._ds = datastore.DataStore()
        self._ds.open_for_write(self._settings.sync_file)

    def _is_control_record(self, record) -> bool:
        return False

    def _process_record(self, record) -> bool:
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

    def _send_mark(self):
        sender_mark = pb.SenderMarkRequest()
        request = pb.Request()
        request.sender_mark.CopyFrom(sender_mark)
        record = pb.Record()
        record.request.CopyFrom(request)
        self._send_record(record)

    def _maybe_send_mark(self):
        """Send mark if we are writting the first record in a block."""
        if self._last_block_end == self._written_block_end:
            return
        self._send_mark()

    def _maybe_request_read(self):
        pass
        # if we are paused
        # and more than one chunk has been written
        # and N time has elapsed
        # send message asking sender to read from last_read_offset to current_offset

    def _write_record(self, record):
        ret = self._ds.write(record)
        assert ret is not None
        (file_offset, data_length, _, _) = ret

        self._last_block_end = self._written_block_end
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
        if self.is_control_record(record):
            return

    def _blocks_behind(self) -> int:
        return 0

    def _maybe_transition_pause(self):
        """Stop sending data to the sender if it is backed up."""
        if self._blocks_behind() < self._threshold_block_high:
            return
        self._state = _SendState.PAUSED
        # self._send_mark()

    def _maybe_transition_restart(self):
        """Start looking for a good opportunity to actively use sender."""
        pass
        # self._mark_position()
        # self._send_mark()

    def _maybe_transition_active(self):
        """Transition to the active state by sending collected records."""
        pass
        # if mark_position received
        #     send(collected records)

    def write(self, record):
        if not self._ds:
            self.open()

        self._process_record(record)
        if not self._is_control_record(record):
            self._write_record(record)

        # Transition sending state machine
        if self._state == _SendState.ACTIVE:
            self._maybe_transition_pause()
        elif self._state == _SendState.PAUSED:
            self._maybe_transition_restart()
        elif self._state == _SendState.RESTARTING:
            self._maybe_transition_active()

        if self._is_control_record(record):
            return

        # Execute sending state machine actions
        if self._state == _SendState.ACTIVE:
            self._send_record(record)
            self._maybe_send_mark()
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
