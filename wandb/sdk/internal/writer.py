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
    |            |            |            |            |
"""

import logging
import enum

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
    ):
        self._settings = settings
        self._record_q = record_q
        self._result_q = result_q
        self._ds = None
        self._chunk_max_threshold = 12
        self._chunk_min_threshold = 4
        # last position inquired from sender
        self._inquiry_position = None
        # last position reported from sender
        self._report_position = None
        # position before last written record
        self._writer_before_position = None
        # position after last written record
        self._writer_after_position = None
        # collection block number
        self._collection_blocknum = None

        # collect records for a pending block while paused
        # because the data isnt available on disk yet
        # and we might want to restart sending
        self._collection_records = []
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

    def _maybe_inquire_sender_position(self):
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

        self._prev_position = self._ds.get_position()
        self._ds.write(record)
        self._next_position = self._ds.get_position()

        self._prev_blocknum = self._prev_position.blocknum
        self._next_blocknum = self._next_position.blocknum

        self._is_paused = True

    def _maybe_resume(self):
        if self._sender_chunks_behind() > self._chunk_min_threshold:
            return
        self._is_paused = False

    def _send_record(self, record):
        # move into send record
        # self._maybe_inquire_sender_position()
        pass

    def _collect_record(self, record):
        # move into send record
        # self._maybe_inquire_position()
        # if self._collection_blocknum != self._next_blocknum:
        #    self._collection_reset()
        pass

    def _maybe_pause(self):
        """Stop sending data to the sender if it is backed up."""
        if self._sender_chunks_behind() > self._chunk_max_threshold:
            return

    def _maybe_restart(self):
        """Start looking for a good opportunity to actively use sender."""
        self._mark_position()

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
        if self._send_state == _SendState.ACTIVE:
            self._send_record(record)
        elif self._send_state == _SendState.PAUSED:
            self._collect_record(record)
            self._maybe_request_read()
        elif self._send_state == _SendState.RESTARTING:
            self._collect_record(record)

    def finish(self):
        # TODO: send final read and collected records
        if self._ds:
            self._ds.close()

    def debounce(self) -> None:
        pass
